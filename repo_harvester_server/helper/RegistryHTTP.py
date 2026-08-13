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

# Proactive pacing before each registry request, in seconds, per registry.
#
# Keyed by registry because the limits are not shared. FAIRsharing's limiter
# behaves like a rolling one-minute budget of roughly a dozen requests, not a
# rate cap: the batch of 2026-08-12 tripped it while averaging 0.24 requests/second
# - twenty times slower than the 5 req/s their own MCP client self-paces at - then
# answered normally for about a minute, then tripped again, in eight bursts.
# Reactive backoff cannot win against a window that long: 1+2+4 seconds of retrying
# lands inside the same exhausted budget, which is why 21 of 28 rate-limited
# repositories exhausted their retries and were reported degraded. Pacing at 5s
# holds us near 12 requests/minute and took that run to zero degraded records.
#
# re3data is deliberately absent: it has never rate-limited us in any run. Pacing
# it alongside FAIRsharing cost 13 minutes of a 33-minute batch for no benefit.
#
# The 5s is inferred from one run, not documented by FAIRsharing. Re-measure after
# a batch and adjust.
REQUEST_DELAY_SECONDS = {
    'fairsharing': 5.0,
}

# Registries we have not measured are not paced: inventing a delay would slow
# every batch down on no evidence.
DEFAULT_REQUEST_DELAY_SECONDS = 0.0

# Never honour a Retry-After longer than this: one registry's advice must not
# stall a 100-repository batch.
MAX_BACKOFF_SECONDS = 60

# How much of a 429 body to keep. Enough to tell Rack::Attack's "Retry later"
# from an nginx error page, not enough to bury the log in HTML.
CAPTURE_BODY_CHARS = 500

# Registries whose rate-limit response we have already recorded this run.
_captured_rate_limits = set()


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


def _capture_rate_limit_response(response, registry, url):
    """Record the first 429 a registry sends us, once per run.

    A rate-limit response is the only direct evidence we get about a registry's
    limiter, and retrying throws it away. The headers settle whether
    ``Retry-After`` is sent at all; the body identifies the layer that sent it
    (Rack::Attack answers ``Retry later``, nginx serves an HTML error page).

    Deliberately logs the *response* headers only. The request headers carry the
    bearer token, and this output is meant to be readable — and forwardable to
    the registry's own team — without leaking our credentials.
    """
    if registry in _captured_rate_limits:
        return
    _captured_rate_limits.add(registry)
    logger.warning(
        "First %s rate-limit response this run, recorded verbatim:\n"
        "  url: %s\n  status: %s\n  headers: %s\n  body[:%s]: %r",
        registry, url, response.status_code, dict(response.headers),
        CAPTURE_BODY_CHARS, (response.text or '')[:CAPTURE_BODY_CHARS],
    )


def request_with_backoff(session, method, url, registry, max_retries=3, **kwargs):
    """Perform an HTTP request, retrying with backoff while the registry answers 429.

    Returns the :class:`requests.Response` for any non-429 status — callers
    still inspect status codes themselves. Raises
    :class:`RegistryUnavailableError` when the registry keeps rate-limiting us
    or the request never completes.
    """
    pacing = REQUEST_DELAY_SECONDS.get(registry, DEFAULT_REQUEST_DELAY_SECONDS)
    for attempt in range(max_retries + 1):
        if pacing:
            time.sleep(pacing)
        try:
            response = session.request(method, url, **kwargs)
        except requests.exceptions.RequestException as e:
            raise RegistryUnavailableError(registry, f"request failed: {e}")

        if response.status_code != 429:
            return response

        _capture_rate_limit_response(response, registry, url)
        rate_limited = response

        if attempt == max_retries:
            break

        wait = _retry_after_seconds(response, attempt)
        logger.warning(
            "%s rate-limited this request (HTTP 429); waiting %ss before retry "
            "%s of %s: %s", registry, wait, attempt + 1, max_retries, url,
        )
        time.sleep(wait)

    # Carry the evidence into the exception too: by the time a degraded harvest
    # is reported, the log line above is thousands of repositories away.
    reason = f"rate limited (HTTP 429), still refused after {max_retries} retries"
    said = (rate_limited.text or '').strip()[:CAPTURE_BODY_CHARS]
    if said:
        reason += f"; registry said: {said!r}"
    raise RegistryUnavailableError(registry, reason)
