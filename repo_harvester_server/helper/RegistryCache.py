"""An in-process cache for registry lookups.

One process, one dict: a single uvicorn process with a thread pool means one
in-memory cache reaches every concurrent caller, with no external store to
run or configure.

Deliberately not Redis and not a file. Nothing here is worth persisting, so a
cold process simply looks things up again.

Batch harvesting passes no cache at all. Each repository appears once in a
batch, so a cache there is dead weight that only grows.

What is cached is the *registry* lookup, never the landing page. An operator
who fixes their JSON-LD and resubmits has to see the fix - that is the whole
point of the tool - so the page is re-fetched every time.
"""
import copy
import logging
import threading
import time
from collections import namedtuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger('RegistryCache')

# What one consultation of the registries produced. A namedtuple so a cached
# entry cannot be reshaped by a reader; the dicts and lists inside it are still
# mutable, which is why the cache hands out deep copies.
RegistryResult = namedtuple('RegistryResult', 're3data fairsharing degraded')

# Registry records change on the scale of months, so an hour is conservative.
# Short enough that an operator who has just registered their repository can
# re-check the same day and see it appear.
COMPLETED_TTL_SECONDS = 3600.0

# A registry we could not reach is re-checked far sooner: a rate limiter or
# outage that has recovered should become visible again in about a minute,
# not sit hidden behind an hour-long cache entry.
DEGRADED_TTL_SECONDS = 60.0

# Anyone can submit unlimited distinct URLs to a public endpoint, and the
# service runs under MemoryMax=1G with Restart=always: an unbounded dict is a
# silent kill-and-restart loop rather than a visible failure.
MAX_ENTRIES = 512

# How long a caller waits for another caller that is already computing its key.
# A waiter is holding one of the four harvest slots, and a leader that has not
# finished within this has already exceeded its own worst case.
WAIT_TIMEOUT_SECONDS = 60.0


class CacheWaitTimeout(Exception):
    """Another caller is still computing this key and took too long.

    The caller must not go and compute it too - that duplicates the expensive
    work this cache exists to prevent, and the extra time would run past the
    reverse proxy's read timeout. Report a degraded lookup instead: the leader
    is still running and will fill the cache for the next visitor.
    """


class _Entry:
    """One key's slot: pending while a caller computes it, then resolved."""

    __slots__ = ('event', 'value', 'error', 'expires_at')

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.error = None
        self.expires_at = None

    @property
    def resolved(self):
        return self.event.is_set()


class RegistryCache:
    """Registry lookups by key, with a TTL and one computation per key.

    :param completed_ttl: seconds a lookup that reached every registry is kept.
    :param degraded_ttl: seconds a lookup that could not reach one is kept.
    :param max_entries: hard cap on stored keys.
    :param wait_timeout: seconds to wait for another caller's computation.
    :param clock: monotonic time source; injected so tests need not sleep.
    """

    def __init__(self, completed_ttl=COMPLETED_TTL_SECONDS,
                 degraded_ttl=DEGRADED_TTL_SECONDS,
                 max_entries=MAX_ENTRIES,
                 wait_timeout=WAIT_TIMEOUT_SECONDS,
                 clock=time.monotonic):
        self._completed_ttl = completed_ttl
        self._degraded_ttl = degraded_ttl
        self._max_entries = max_entries
        self._wait_timeout = wait_timeout
        self._clock = clock
        # Guards _entries only. Never held across a computation or a wait.
        self._lock = threading.Lock()
        self._entries = {}

    def _ttl_for(self, result):
        """A mixed result takes the short TTL.

        One registry answered and another did not: re-asking the one that
        answered costs little, and caching the hole where the other one should
        be for a full hour costs a visitor an incomplete record.
        """
        return self._degraded_ttl if result.degraded else self._completed_ttl

    def get_or_compute(self, key, compute):
        """Return the cached result for ``key``, computing it at most once.

        Concurrent callers for the same key do not each compute: the first one
        does, the rest wait for it.

        :param key: any hashable identifying this lookup.
        :param compute: zero-argument callable returning a RegistryResult.
        :raises CacheWaitTimeout: another caller held the key too long.
        """
        entry, is_leader = self._claim(key)
        if is_leader:
            return self._compute_as_leader(key, entry, compute)
        return self._await_leader(key, entry)

    def _claim(self, key):
        """Find or create this key's entry. Returns (entry, is_leader)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.resolved:
                if self._clock() < entry.expires_at:
                    return entry, False
                # Expired. Drop it and compute again.
                del self._entries[key]
                entry = None
            if entry is None:
                entry = _Entry()
                self._entries[key] = entry
                return entry, True
            # Present but not resolved: someone else is computing it.
            return entry, False

    def _compute_as_leader(self, key, entry, compute):
        try:
            value = compute()
            with self._lock:
                entry.value = value
                entry.expires_at = self._clock() + self._ttl_for(value)
                self._evict_if_needed(key)
        except BaseException as e:
            # Do not cache a failure: the next caller should try again rather
            # than inherit it. Waiters already blocked on this entry still get
            # the exception, so they do not wait out the full timeout. This
            # also covers a failure after compute() returns - e.g. compute
            # handing back something _ttl_for cannot read - so the key is
            # never left permanently pending.
            with self._lock:
                self._entries.pop(key, None)
            entry.error = e
            entry.event.set()
            raise
        entry.event.set()
        return copy.deepcopy(value)

    def _await_leader(self, key, entry):
        if not entry.resolved:
            if not entry.event.wait(self._wait_timeout):
                raise CacheWaitTimeout(
                    f"another lookup of {key!r} has been running for more than "
                    f"{self._wait_timeout}s"
                )
        if entry.error is not None:
            raise entry.error
        return copy.deepcopy(entry.value)

    def _evict_if_needed(self, protect_key):
        """Trim to max_entries. Caller must hold self._lock.

        Pending entries are never evicted - another thread is waiting on one.
        Expired entries go before live ones.
        """
        if len(self._entries) <= self._max_entries:
            return
        now = self._clock()
        expired = [
            k for k, e in self._entries.items()
            if k != protect_key and e.resolved and e.expires_at <= now
        ]
        live = [
            k for k, e in self._entries.items()
            if k != protect_key and e.resolved and e.expires_at > now
        ]
        for k in expired + live:
            del self._entries[k]
            if len(self._entries) <= self._max_entries:
                return
