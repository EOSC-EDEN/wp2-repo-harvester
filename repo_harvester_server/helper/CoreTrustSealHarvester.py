"""CoreTrustSeal's own certificate list, from the GraphQL API behind
https://amt.coretrustseal.org/certificates.

certificates() takes no arguments, so there is no search by repository: the
whole list (about 300 certificates, 200 KB) is fetched once and matched here.
"""
import logging
import threading
import time
from datetime import date

import requests

from repo_harvester_server.helper import UrlMatching
from repo_harvester_server.helper.CertificateHelper import DOI_PATTERN, clean_certificate
from repo_harvester_server.helper.RegistryHTTP import (
    RegistryUnavailableError,
    request_with_backoff,
)

GRAPHQL_QUERY = {"operationName":"getCertificates","variables":{},"query":"query getCertificates  {certificates {id\ncertificationRequest {certificate {id\ncertificateFileKey} repository {description\nid\nname\npid\nwebsite\ninstitution { address\ncity\ncountry\nemail\nname }}reviewDueDate\nreviewLoopIteration\nstatus\nvalidUntil\nuuid\npidUrl}}}"}


def _doi(value):
    match = DOI_PATTERN.search(value or '')
    return match.group().lower() if match else None


def _still_valid(valid_until):
    """CoreTrustSeal publishes no status, so it is worked out from validUntil.
    The answer is the one on harvest day: a stored graph keeps saying active
    after the date passes, until the repository is harvested again."""
    try:
        return date.fromisoformat(valid_until) >= date.today()
    except (TypeError, ValueError):
        return None


def _group_by_repository(certificates):
    """Certification requests per repository.

    CoreTrustSeal sometimes files a renewal under a new repository.id (4TU: 130
    and 343), so a request joins a group with the same pid DOI or the same name.
    """
    groups, by_key = [], {}
    for cert in certificates:
        request = (cert or {}).get('certificationRequest')
        if not request:
            continue
        repository = request.get('repository') or {}
        keys = [k for k in (('pid', _doi(repository.get('pid'))),
                            ('name', (repository.get('name') or '').strip().casefold()))
                if k[1]]
        group = next((by_key[k] for k in keys if k in by_key), None)
        if group is None:
            group = []
            groups.append(group)
        group.append(request)
        for k in keys:
            by_key.setdefault(k, group)
    return groups


class CoreTrustSealHarvester(object):

    logger = logging.getLogger('CoreTrustSealHarvester')

    graphql_endpoint = 'https://backend.amt.coretrustseal.org/graphql'
    # Certificates change on the scale of weeks; a server that runs for months
    # should still pick up a new one the next day.
    REFRESH_SECONDS = 24 * 3600
    # After a failed fetch, wait this long before the next try, so an endpoint
    # that is down costs one timeout per hour rather than one per repository.
    RETRY_SECONDS = 3600
    # The server runs several harvests at once; the ones that arrive while the
    # list is being fetched wait for it rather than fetching it again.
    LOCK_TIMEOUT_SECONDS = 60

    def __init__(self):
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._groups = None
        self._next_fetch = 0.0
        self._failure = None

    def harvest(self, catalog_urls, re3data_meta=None):
        """The CoreTrustSeal record for a repository, or None if it has none.

        Exact keys first, both from re3data: the repository's re3data DOI as
        CoreTrustSeal's repository.pid, then re3data's certificate DOI as a
        pidUrl. Without either, the website by UrlMatching, where a host-only
        match counts (batch URLs are often deeper pages than the root
        CoreTrustSeal records) and a tie is no match.
        """
        self.logger.info("-- Harvesting from CoreTrustSeal -- ")
        groups = self._certificate_groups()
        group = self._match_by_key(groups, re3data_meta or {})
        if group is None:
            group = self._match_by_url(groups, catalog_urls)
        return self._record(group) if group else None

    def _certificate_groups(self):
        if not self._lock.acquire(timeout=self.LOCK_TIMEOUT_SECONDS):
            raise RegistryUnavailableError(
                'coretrustseal',
                f'gave up after {self.LOCK_TIMEOUT_SECONDS}s waiting for another '
                'request to fetch the certificate list')
        try:
            if time.monotonic() >= self._next_fetch:
                try:
                    self._groups = _group_by_repository(self._fetch())
                    self._next_fetch = time.monotonic() + self.REFRESH_SECONDS
                except RegistryUnavailableError as e:
                    self._next_fetch = time.monotonic() + self.RETRY_SECONDS
                    self._failure = e.reason
                    if self._groups is not None:
                        self.logger.warning('%s - using the list fetched earlier', e)
            if self._groups is None:
                raise RegistryUnavailableError('coretrustseal', self._failure)
            return self._groups
        finally:
            self._lock.release()

    def _fetch(self):
        self.logger.info('Fetching the CoreTrustSeal certificate list')
        response = request_with_backoff(
            self.session, 'POST', self.graphql_endpoint, 'coretrustseal',
            json=GRAPHQL_QUERY, headers={'Accept': 'application/json'}, timeout=30,
        )
        if response.status_code != 200:
            raise RegistryUnavailableError(
                'coretrustseal', f'HTTP {response.status_code} from {self.graphql_endpoint}')
        try:
            return response.json()['data']['certificates']
        except (ValueError, KeyError, TypeError) as e:
            raise RegistryUnavailableError(
                'coretrustseal', f'unexpected answer from {self.graphql_endpoint}: {e!r}')

    def _match_by_key(self, groups, re3data_meta):
        re3data_dois = {_doi(i) for i in re3data_meta.get('identifier') or []
                        if '10.17616/' in str(i)}
        certificate_dois = {_doi(c.get('url')) for c in re3data_meta.get('certificates') or []} - {None}
        by_pid = next((g for g in groups if any(
            _doi((r.get('repository') or {}).get('pid')) in re3data_dois for r in g)), None)
        return by_pid or next((g for g in groups if any(
            _doi(r.get('pidUrl')) in certificate_dois for r in g)), None)

    def _match_by_url(self, groups, catalog_urls):
        scored = [(max(UrlMatching.url_score(catalog_urls, (r.get('repository') or {}).get('website'))
                       for r in g), g)
                  for g in groups]
        best = max((score for score, _ in scored), default=0)
        if best == 0:
            return None
        winners = [g for score, g in scored if score == best]
        if len(winners) > 1:
            self.logger.info(
                'CoreTrustSeal: %s repositories match %s equally well (%s), taking none',
                len(winners), ' | '.join(catalog_urls),
                ', '.join((g[0].get('repository') or {}).get('name') or '?' for g in winners))
            return None
        return winners[0]

    def _record(self, group):
        """Repository info from the latest certification, plus every
        certificate, expired ones included: each has its own DOI and dct:valid
        says which one holds. CoreTrustSeal's own `status` is the request
        workflow (Accepted for all), not validity, so it is not used."""
        latest = max(group, key=lambda r: r.get('validUntil') or '')
        repository = latest.get('repository') or {}
        institution = repository.get('institution') or {}
        record = {
            'resource_type': 'cts:Repository',
            'title': repository.get('name'),
            'identifier': [i for i in (repository.get('pid'), repository.get('website')) if i],
            'description': repository.get('description'),
            'certificates': [c for c in (clean_certificate({
                'url': r.get('pidUrl'),
                'name': 'CoreTrustSeal',
                'issuer': 'CoreTrustSeal',
                'expires': r.get('validUntil'),
                'active': _still_valid(r.get('validUntil')),
            }) for r in group) if c],
        }
        if institution.get('name'):
            # country under the publisher: the export reads it from there only
            record['publisher'] = {'name': institution['name'], 'country': institution.get('country')}
        if institution.get('email'):
            record['contact'] = {'email': institution['email']}
        return {k: v for k, v in record.items() if v}


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(CoreTrustSealHarvester().harvest(sys.argv[1:]), indent=2))
