"""Shared HTTP plumbing for the external registry harvesters.

Two concerns live here:

  * Telling "the registry has no such record" apart from "we never got an
    answer". The first stays a plain ``None`` return in the harvesters; the
    second raises :class:`RegistryUnavailableError` so the caller can report a
    degraded harvest instead of silently recording a miss.
  * Backing off politely when a registry rate-limits us (HTTP 429) instead of
    hammering an endpoint that has just told us to stop.
"""
import logging
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger('RegistryHTTP')

# Proactive pacing between registry requests, in seconds. Kept at 0 until
# FAIRsharing tells us an acceptable request rate (asked 2026-08-10); raising it
# slows a whole batch down without touching any call site.
REQUEST_DELAY_SECONDS = 0.0

# Never honour a Retry-After longer than this: one registry's advice must not
# stall a 100-repository batch.
MAX_BACKOFF_SECONDS = 60


class RegistryUnavailableError(Exception):
    """A registry could not be consulted at all.

    Covers rate limiting, timeouts and transport errors — anything that leaves
    us without an answer. Deliberately distinct from "consulted successfully,
    no matching record", which stays a ``None`` return, because conflating the
    two is what let a rate-limited batch report itself as a clean success.

    Raised by the helper layer only; never turned into sys.exit() inside
    repo_harvester_server/ so the connexion API keeps running (callers such as
    harvest_all.py decide the exit code).
    """

    def __init__(self, registry, reason):
        self.registry = registry
        self.reason = reason
        super().__init__(f"{registry} could not be consulted: {reason}")


def _retry_after_seconds(response, attempt):
    """Seconds to wait before the next attempt.

    Honours the server's Retry-After when it sends a usable one, otherwise
    falls back to exponential backoff (1, 2, 4, ...). Whether FAIRsharing sends
    the header at all is still an open question with their team, so both paths
    have to work.
    """
    header = response.headers.get('Retry-After')
    if header:
        try:
            # Clamp both ways: negative values would make time.sleep() raise and abort
            # the batch, violating the "degrade, don't abort" principle.
            return max(0, min(int(header), MAX_BACKOFF_SECONDS))
        except (TypeError, ValueError):
            # Retry-After may be an HTTP-date rather than a delay in seconds.
            logger.info("Ignoring unparseable Retry-After header: %r", header)
    return min(2 ** attempt, MAX_BACKOFF_SECONDS)


def request_with_backoff(session, method, url, registry, max_retries=3, **kwargs):
    """Perform an HTTP request, retrying with backoff while the registry answers 429.

    Returns the :class:`requests.Response` for any non-429 status — callers
    still inspect status codes themselves. Raises
    :class:`RegistryUnavailableError` when the registry keeps rate-limiting us
    or the request never completes.
    """
    for attempt in range(max_retries + 1):
        if REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS)
        try:
            response = session.request(method, url, **kwargs)
        except requests.exceptions.RequestException as e:
            raise RegistryUnavailableError(registry, f"request failed: {e}")

        if response.status_code != 429:
            return response

        if attempt == max_retries:
            break

        wait = _retry_after_seconds(response, attempt)
        logger.warning(
            "%s rate-limited this request (HTTP 429); waiting %ss before retry "
            "%s of %s: %s", registry, wait, attempt + 1, max_retries, url,
        )
        time.sleep(wait)

    raise RegistryUnavailableError(
        registry, f"rate limited (HTTP 429), still refused after {max_retries} retries"
    )
