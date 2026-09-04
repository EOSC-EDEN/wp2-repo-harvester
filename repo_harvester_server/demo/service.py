"""The one harvest both public faces call.

The steps are spelled out here rather than calling RepositoryHarvester.harvest()
because persistence and harmonisation must follow configuration instead of
being unconditional: the same code has to serve a stateless public demo (an
empty FUSEKI_PATH, nothing written or harmonized) and a developer or batch
machine with a triple store (FUSEKI_PATH set or left unset, behaving exactly
like harvest() always did). config.PERSISTENCE_ENABLED is that switch, and it
is on unless FUSEKI_PATH is explicitly emptied.

The response shape is unchanged for the JSON API either way: export_and_save
appends to final_records before its `if save:` block and returns the same list
regardless, and harvest() discarded the harmonized record rather than
returning it, so the controller was already serving raw per-source records.
"""
import logging
import threading

from repo_harvester_server import config
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.RegistryCache import RegistryCache
from repo_harvester_server.helper.RegistryHTTP import RegistryUnavailableError
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger('DemoService')

# A harvest is a burst of slow outbound requests, so unbounded concurrency turns
# this service into both a self-inflicted outage and a nuisance amplifier toward
# third-party sites. The cap sits below the ten WSGI worker threads connexion's
# a2wsgi bridge runs, so the form, the error pages and /healthz stay answerable
# while the maximum number of harvests is in flight.
MAX_CONCURRENT_HARVESTS = 4

_harvest_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HARVESTS)

# One cache for the whole process. The app is a single uvicorn process with a
# thread pool, so this reaches every concurrent visitor - which is the case
# that breaks without it: a room full of workshop participants pasting the same
# repository URL, each triggering its own registry lookups.
#
# Only the registry lookup is cached, never the landing page. A repository
# operator who fixes their JSON-LD and resubmits has to see the fix; that is
# what this tool is for.
_registry_cache = RegistryCache()

# One FAIRsharing sign-in per process instead of one per visitor. Built lazily
# so a deployment with FAIRsharing switched off never signs in at all.
_fairsharing_harvester = None
_fairsharing_harvester_lock = threading.Lock()

# How long a caller waits for another caller that is already building the
# shared harvester. Bounded like every other lock in the chain beneath this
# one - FAIRsharingHarvester._lock at 60s, RegistryCache's waiter at 60s - so
# a visitor who only wants to wait for someone else's sign-in still gets a
# page rather than blocking past nginx's proxy_read_timeout. _authenticate()
# retries through request_with_backoff (up to MAX_BACKOFF_SECONDS per
# attempt), so a sign-in against a rate-limiting FAIRsharing can run well
# past this 30s; that is deliberately shorter than
# FAIRsharingHarvester.LOCK_TIMEOUT_SECONDS's own 60s cap, so a caller stuck
# here gives up before that inner lock would even time out on its own.
_FAIRSHARING_HARVESTER_BUILD_TIMEOUT_SECONDS = 30.0


class _FairsharingUnavailable:
    """Stood in for the shared harvester when it could not be built.

    Every call raises RegistryUnavailableError immediately - the same signal
    a reachable-but-failing FAIRsharing produces - so _try_registry catches it
    and records 'fairsharing' as degraded instead of found or missing.

    This has to be a truthy object rather than None. RepositoryHarvester's
    __init__ stores whatever it is handed as self.fairsharing_harvester, and
    _consult_registries only falls back to building (and signing in) its own
    FAIRsharingHarvester when that attribute is falsy:
    'self.fairsharing_harvester or FAIRsharingHarvester()'. Handing back None
    on a degrade path would trigger exactly that fallback - a brand new,
    per-visitor construction with no timeout at all (RegistryHTTP's rate gate
    has none, and a sign-in can retry up to MAX_BACKOFF_SECONDS per attempt) -
    right when the process is already too congested to build the shared one
    in time. A stub sidesteps the fallback entirely while still degrading
    this one repository honestly.
    """

    def __init__(self, reason):
        self._reason = reason

    def _unavailable(self):
        raise RegistryUnavailableError('fairsharing', self._reason)

    def harvest(self, *args, **kwargs):
        self._unavailable()

    def harvest_by_id(self, *args, **kwargs):
        self._unavailable()


def shared_fairsharing_harvester():
    """The one FAIRsharing harvester for this process.

    Returns None only when FAIRsharing is switched off by configuration - the
    one case where "no harvester" is the correct, final answer rather than a
    degradation. When it is switched on but could not be built in time or at
    all, this returns a stub that raises RegistryUnavailableError on every
    call instead: see _FairsharingUnavailable for why None would be wrong
    there.

    Every harvest used to construct its own, and that constructor signs in - so
    each visitor cost a sign-in, and the sign-in pays the pacing delay before
    it asks anything.

    Returned even when the credentials are missing. _authenticate() makes no
    network call in that case, so a credential-less harvester is free to build,
    and returning the "switched off" None here would send
    harvest_registry_metadata down its "or FAIRsharingHarvester()" fallback and
    construct a fresh one per harvest - exactly what this exists to avoid. A
    misconfigured registry is already reported as such on the page, separately
    from an unreachable one.

    Two ways this degrades instead of failing the harvest: giving up on the
    lock after _FAIRSHARING_HARVESTER_BUILD_TIMEOUT_SECONDS, and construction
    itself raising - e.g. a sign-in response that parses as JSON but is not a
    dict. Either way the module-level singleton is left as it was (None, if
    this was the first attempt) so the next caller retries rather than
    inheriting a wedged state - only the stub returned to *this* caller
    carries the failure.
    """
    if 'fairsharing' not in config.ENABLED_REGISTRIES:
        return None
    global _fairsharing_harvester
    # Held across construction on purpose: the alternative is four worker
    # threads signing in at once on the first busy moment.
    if not _fairsharing_harvester_lock.acquire(
        timeout=_FAIRSHARING_HARVESTER_BUILD_TIMEOUT_SECONDS
    ):
        logger.warning(
            "Gave up waiting %ss to build the shared FAIRsharing harvester - "
            "this is our own construction queue, not a FAIRsharing rate "
            "limit. Continuing this harvest without FAIRsharing.",
            _FAIRSHARING_HARVESTER_BUILD_TIMEOUT_SECONDS,
        )
        return _FairsharingUnavailable(
            f"gave up waiting {_FAIRSHARING_HARVESTER_BUILD_TIMEOUT_SECONDS}s "
            "for our own FAIRsharing-harvester construction queue, not a "
            "FAIRsharing rate limit"
        )
    try:
        if _fairsharing_harvester is None:
            try:
                _fairsharing_harvester = FAIRsharingHarvester()
            except Exception:
                logger.error(
                    "Could not build the shared FAIRsharing harvester; this "
                    "harvest and the next caller will continue without "
                    "FAIRsharing.", exc_info=True,
                )
                return _FairsharingUnavailable(
                    "the shared FAIRsharing harvester failed to build (its "
                    "sign-in against https://api.fairsharing.org raised) - "
                    "check FAIRSHARING_USERNAME/FAIRSHARING_PASSWORD and "
                    "connectivity, then see the log for the underlying error"
                )
        return _fairsharing_harvester
    finally:
        _fairsharing_harvester_lock.release()


class HarvesterBusyError(Exception):
    """Every harvest slot is in use. Recoverable: the caller should retry."""


def collect_services(records):
    """Every service named in a list of exported DCAT records.

    Services sit either at the top level or nested under foaf:primaryTopic, and
    either as a list or as a single object.
    """
    services = []
    for record in records:
        if not isinstance(record, dict):
            continue
        containers = [record]
        primary_topic = record.get('foaf:primaryTopic')
        if isinstance(primary_topic, dict):
            containers.append(primary_topic)
        for container in containers:
            found = container.get('dcat:service', [])
            if isinstance(found, list):
                services.extend(found)
            elif found:
                services.append(found)
    return services


def _self_hosted_rows(harvester, found_sources):
    """One row per self-hosted extractor: found, checked-and-missing, or not reached."""
    rows = []
    for source, label in harvester.extractors.items():
        if source in harvester.REGISTRY_NAMES:
            continue
        if source in found_sources:
            status = 'found'
        elif source in harvester.attempted_sources:
            status = 'missing'
        else:
            status = 'not_checked'
        rows.append({'source': source, 'label': label, 'status': status})
    return rows


def _registry_rows(harvester, found_sources, records):
    """One row per registry, keeping 'switched off' distinct from 'unreachable'."""
    display_names = getattr(harvester, 'REGISTRY_DISPLAY_NAMES', {})
    rows = []
    for name in harvester.REGISTRY_NAMES:
        if name in harvester.disabled_registries:
            status = 'disabled'
        elif name in getattr(harvester, 'misconfigured_registries', ()):
            status = 'misconfigured'
        elif name in harvester.degraded_sources:
            status = 'unavailable'
        elif name in found_sources:
            status = 'found'
        else:
            status = 'no_record'
        record = next(
            (r for r in records
             if isinstance(r, dict)
             and str(r.get('@id', '')).startswith(f'eden://harvester/{name}/')),
            None,
        )
        rows.append({
            'name': name,
            'display_name': display_names.get(name, name),
            'label': harvester.extractors.get(name, name),
            'status': status,
            'record': record,
        })
    return rows


def build_report(harvester, submitted_url, records):
    """Turn a finished harvest into the structure the page and the API render."""
    found_sources = {
        m.get('source') for m in harvester.metadata if m.get('metadata')
    }
    return {
        'submitted_url': submitted_url,
        'canonical_url': harvester.catalog_url,
        'page_fetched': harvester.metadata_helper is not None,
        'self_hosted': _self_hosted_rows(harvester, found_sources),
        'registries': _registry_rows(harvester, found_sources, records),
        'services': collect_services(records),
        'records': records,
    }


def run_interactive_harvest(url):
    """Harvest one repository for one visitor.

    Whether anything is written or harmonized follows config.PERSISTENCE_ENABLED
    (true exactly when FUSEKI_PATH is set): nothing on the stateless public
    demo, both on a machine configured with a triple store.

    :param url str: the repository landing page URL.
    :raises HarvesterBusyError: every concurrent slot is taken.
    """
    if not _harvest_slots.acquire(blocking=False):
        logger.warning("All %s harvest slots busy, refusing: %s", MAX_CONCURRENT_HARVESTS, url)
        raise HarvesterBusyError(
            "All harvest slots are busy right now. Please try again in a moment."
        )
    try:
        harvester = RepositoryHarvester(
            url,
            persist=config.PERSISTENCE_ENABLED,
            fairsharing_harvester=shared_fairsharing_harvester(),
            registry_cache=_registry_cache,
        )
        harvester.harvest_self_hosted_metadata()
        harvester.harvest_registry_metadata()
        records = harvester.export_and_save(save=config.PERSISTENCE_ENABLED)
        if config.PERSISTENCE_ENABLED:
            try:
                harvester.harmonize()
            except Exception:
                logger.error(
                    "Harmonization failed after harvesting %s; continuing with "
                    "the raw per-source records.", url, exc_info=True
                )
        return build_report(harvester, url, records)
    finally:
        _harvest_slots.release()
