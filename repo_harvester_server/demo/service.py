"""The one harvest both public faces call.

Deliberately not RepositoryHarvester.harvest(): that always persists
(export_and_save(True)) and then harmonizes, and this deployment wants
neither. Harmonisation is a registry concern, not a diagnostic-tool concern,
and the service is stateless - so the steps are spelled out instead.

The response shape is unchanged for the JSON API: export_and_save appends to
final_records before its `if save:` block and returns the same list either way,
and harvest() discarded the harmonized record rather than returning it, so the
controller was already serving raw per-source records.
"""
import logging
import threading

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
    rows = []
    for name in harvester.REGISTRY_NAMES:
        if name in harvester.disabled_registries:
            status = 'disabled'
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
    """Harvest one repository for one visitor. Nothing is written anywhere.

    :param url str: the repository landing page URL.
    :raises HarvesterBusyError: every concurrent slot is taken.
    """
    if not _harvest_slots.acquire(blocking=False):
        logger.warning("All %s harvest slots busy, refusing: %s", MAX_CONCURRENT_HARVESTS, url)
        raise HarvesterBusyError(
            "All harvest slots are busy right now. Please try again in a moment."
        )
    try:
        harvester = RepositoryHarvester(url, persist=False)
        harvester.harvest_self_hosted_metadata()
        harvester.harvest_registry_metadata()
        records = harvester.export_and_save(save=False)
        return build_report(harvester, url, records)
    finally:
        _harvest_slots.release()
