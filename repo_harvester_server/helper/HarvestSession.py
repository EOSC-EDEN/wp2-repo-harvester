"""One HTTP session for everything the harvester fetches from the open web.

The harvester does not only fetch the URL it is given: it follows redirects and
it fetches URLs it *discovers inside* that page - linkset URLs from `Link`
headers, typed links, robots.txt. On a public endpoint those targets are chosen
by whoever controls the submitted page, so a landing page can aim the server at
an instance metadata service or at a private neighbour. Validating the
submitted URL at the front door cannot see any of them, which is why the guard
sits on a mounted adapter instead: requests re-selects the adapter for every
redirect hop, so this is the one place that sees every URL actually fetched.

Two guarantees, for every request and every hop:

  * the target is http(s) and resolves to a globally routable address;
  * a request without an explicit timeout gets a default one, so no fetch can
    hang forever.

Known limit: the address is checked at send time and resolved again by the
connection, so a DNS record that changes between the two is not caught. Closing
that needs connection-level address pinning, which is not worth its cost for a
stateless service that holds nothing worth stealing.
"""
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger('HarvestSession')

# (connect, read). The read timeout is generous on purpose: some repository
# landing pages really are slow, and a premature timeout reads to the operator
# as "your site is broken" when it is not.
DEFAULT_TIMEOUT = (5, 20)

ALLOWED_SCHEMES = ('http', 'https')

USER_AGENT = 'EDEN-Harvester/1.0 (Research Project; mailto:eosceden@uni-bremen.de)'
ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

# Set this to harvest a repository on a private network - a local test server,
# an institutional host that is not publicly routable. Off by default so a
# public deployment is guarded without anyone having to remember a setting.
ALLOW_PRIVATE_TARGETS_ENV = 'EDEN_ALLOW_PRIVATE_TARGETS'

_TRUE_VALUES = ('1', 'true', 'yes', 'on')


def _private_targets_allowed():
    # Read per call, not at import: tests and operators change it at runtime.
    return os.environ.get(ALLOW_PRIVATE_TARGETS_ENV, '').strip().lower() in _TRUE_VALUES


def _refuse(message):
    """Log the refusal, then raise it.

    A refusal here can be a submitted typo or it can be an address probe
    (e.g. the AWS/GCP/Azure metadata address) - on a public endpoint the two
    look identical unless the reason is on record, so every refusal is logged
    at WARNING before it is raised.
    """
    logger.warning(message)
    raise BlockedTargetError(message)


def assert_target_allowed(url):
    """Raise BlockedTargetError unless this URL may be fetched.

    :param url str: the absolute URL about to be requested.
    """
    try:
        parsed = urlparse(url)
    except ValueError as e:
        _refuse(f"refusing to fetch {url}: invalid URL ({e})")

    if parsed.scheme not in ALLOWED_SCHEMES:
        _refuse(f"refusing to fetch {url}: only http and https targets are followed")
    host = parsed.hostname
    if not host:
        _refuse(f"refusing to fetch {url}: the URL names no host")

    if _private_targets_allowed():
        return

    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, ValueError) as e:
        _refuse(f"refusing to fetch {url}: {host} does not resolve ({e})")

    for info in infos:
        # Link-local addresses can carry a %scope suffix that ip_address rejects.
        address = ipaddress.ip_address(info[4][0].split('%')[0])
        if not address.is_global:
            _refuse(
                f"refusing to fetch {url}: {host} resolves to {address}, which is not "
                "a public address"
            )


class BlockedTargetError(requests.exceptions.RequestException):
    """A request was refused before it left the process.

    Subclasses RequestException on purpose: every caller in the harvester
    already treats a RequestException as "this fetch did not work", so a
    blocked target degrades one source instead of failing a whole harvest.
    """


class GuardedHTTPAdapter(HTTPAdapter):
    """Applies the guard and the default timeout to every hop."""

    def send(self, request, **kwargs):
        assert_target_allowed(request.url)
        if kwargs.get('timeout') is None:
            kwargs['timeout'] = DEFAULT_TIMEOUT
        return super().send(request, **kwargs)


def build_session():
    """A session whose every request is guarded, time-limited and identified."""
    session = requests.Session()
    adapter = GuardedHTTPAdapter()
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({'User-Agent': USER_AGENT, 'Accept': ACCEPT})
    return session
