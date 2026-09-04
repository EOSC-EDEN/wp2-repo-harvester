import os
import json
import threading
from contextlib import contextmanager

import jmespath
import requests
from urllib.parse import urlparse
import logging
from repo_harvester_server.helper.JMESPATHQueries import FAIRSHARING_QUERY
from repo_harvester_server.helper.RegistryHTTP import (
    RegistryUnavailableError,
    request_with_backoff,
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# Hostname labels that name infrastructure rather than a repository. Searching
# FAIRsharing for one of these returns 25 arbitrary records, takes seconds of
# their server's time, and can never survive the hostname filter afterwards.
# Deliberately short and strictly infrastructural: real repository names live in
# this position too ('cds' is the Copernicus Data Store, 'radar' is Oxford
# Brookes' repository), and suppressing those would lose records.
GENERIC_HOST_LABELS = frozenset({
    'www', 'www2', 'web', 'data', 'database', 'opendata', 'repository', 'repo',
    'archive', 'catalog', 'catalogue', 'portal', 'api', 'site', 'library',
    'db', 'dv', 'eprints',
})

# How long a harvest waits for another harvest that is already talking to
# FAIRsharing. One harvester now serves every visitor, and its work is
# serialised, so a busy moment queues rather than overlapping. Bounded because
# a visitor waiting behind three others must still get a page: nginx gives up
# at 120s, and an honest "FAIRsharing could not be consulted" beats a gateway
# error. The wait is our own queue, not their rate limiter - the log says so.
#
# 60.0, not 30.0: a cold harvest holds this lock across both search
# strategies in harvest() (see harvest()'s docstring), each paying the
# pacing gate's REQUEST_DELAY_SECONDS['fairsharing'] (7.5s) before it fires,
# so one harvest can occupy the lock for roughly 15s. Under sustained load a
# third concurrent visitor asking about a *distinct* URL (so not served by
# the registry cache) could queue behind two such harvests and cross a 30s
# cap while nothing was actually wrong, and be told FAIRsharing "could not
# be consulted" for it. 60.0 matches RegistryCache's own waiter timeout and
# still leaves headroom inside nginx's 120s proxy_read_timeout. This is
# reasoned from the pacing and lock-holding arithmetic above, not measured
# against real demo load - like REQUEST_DELAY_SECONDS in RegistryHTTP.py,
# re-measure and adjust once a busy session gives us something to learn
# from.
LOCK_TIMEOUT_SECONDS = 60.0


class FAIRsharingHarvester:
    """
    A harvester for fetching metadata from the FAIRsharing.org registry.
    Handles authentication and searching for repository records.
    """
    logger = logging.getLogger('FAIRsharingHarvester')

    def __init__(self):
        self.api_url = "https://api.fairsharing.org"
        self.jwt_token = None
        # One session for sign-in and every search: reuses the TCP/TLS
        # connection instead of shaking hands once per request.
        self.session = requests.Session()
        # One harvester is shared across every visitor on the public demo, so
        # its Session and its JWT are reached by four worker threads.
        # requests.Session is not documented thread-safe, and the sequence
        # "read token, search, re-authenticate on 401, search again" has to be
        # atomic or two threads both sign in and one overwrites the other's
        # fresher token. Reentrant because harvest() -> _search_fairsharing()
        # -> _authenticate() takes it again on the way down.
        #
        # Serialising is not only about safety: the 5-second pacing was
        # measured against a single sequential stream, and four independent
        # threads would spend four times that budget.
        self._lock = threading.RLock()
        self._authenticate()

    @contextmanager
    def _serialized(self):
        """Hold the harvester for this thread, or degrade rather than queue
        forever."""
        if not self._lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
            self.logger.warning(
                "Gave up waiting %ss for the FAIRsharing harvester - this is "
                "our own request queue, not a FAIRsharing rate limit",
                LOCK_TIMEOUT_SECONDS,
            )
            raise RegistryUnavailableError(
                'fairsharing',
                f"another harvest held the FAIRsharing session for more than "
                f"{LOCK_TIMEOUT_SECONDS}s",
            )
        try:
            yield
        finally:
            self._lock.release()

    def _authenticate(self):
        """
        Authenticates with the FAIRsharing API using environment variables.
        """
        # Note: _serialized() can itself raise RegistryUnavailableError (a
        # lock-acquire timeout) before the try/except below is even reached,
        # which would break the "must not fail" promise on that except path.
        # Unreachable today - __init__ takes a fresh lock, and the only other
        # caller (_search_fairsharing()'s 401 retry) is already holding it,
        # reentrant - but becomes reachable the day something calls
        # _authenticate() directly from a second thread, e.g. a background
        # token refresh.
        with self._serialized():
            username = os.environ.get('FAIRSHARING_USERNAME')
            password = os.environ.get('FAIRSHARING_PASSWORD')

            if not username or not password:
                self.logger.warning("FAIRSHARING_USERNAME and/or FAIRSHARING_PASSWORD environment variables not set. Authentication will fail.")
                return

            url = f"{self.api_url}/users/sign_in"
            payload = {"user": {"login": username, "password": password}}
            headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

            try:
                response = request_with_backoff(
                    self.session, 'POST', url, 'fairsharing',
                    headers=headers, data=json.dumps(payload), timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                self.jwt_token = data.get('jwt')
                if self.jwt_token:
                    self.logger.info("Successfully authenticated with FAIRsharing.")
            except RegistryUnavailableError as e:
                # Deliberately not re-raised: the caller may be constructing one
                # shared harvester for a whole batch, and that must not fail. An
                # unset token degrades each repository individually instead.
                self.logger.error("Could not sign in to FAIRsharing: %s", e)
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to authenticate with FAIRsharing: {e}")

    def harvest(self, catalog_url, repository_name=None):
        """
        Public method to harvest metadata for a given URL.

        ``repository_name`` is the repository's real name when the caller knows
        it, and is what the fallback search should ask for. Callers that only
        have a URL (the connexion controller) may omit it, and the fallback then
        guesses from the hostname.
        """
        with self._serialized():
            if not self.jwt_token:
                raise RegistryUnavailableError(
                    'fairsharing',
                    "not signed in - check the FAIRSHARING_USERNAME and "
                    "FAIRSHARING_PASSWORD environment variables",
                )

            self.logger.info("Harvesting from FAIRsharing...")
            hostname = urlparse(catalog_url).hostname
            if not hostname:
                return None

            # Strategy 1: Search by hostname
            self.logger.info(f"Strategy 1: Searching FAIRsharing by hostname: '{hostname}'")
            metadata = self._search_fairsharing(hostname, hostname_filter=hostname)
            if metadata:
                self.logger.info(f"SUCCESS: Found FAIRsharing record via hostname search: {metadata.get('title')}")
                return metadata

            # Strategy 2: Search by repository name
            search_name = repository_name or self._name_from_hostname(hostname)
            if search_name:
                self.logger.info(f"Strategy 2: Retrying FAIRsharing search with repository name: '{search_name}'")
                metadata = self._search_fairsharing(search_name, hostname_filter=hostname)
                if metadata:
                    self.logger.info(f"SUCCESS: Found FAIRsharing record via name search: {metadata.get('title')}")
                    return metadata

            self.logger.info(
                "FAIRsharing has no record matching '%s' (searched by hostname%s).",
                hostname, " and name" if search_name else "",
            )
            return None

    def _name_from_hostname(self, hostname):
        """Guess a searchable repository name from a hostname, or None.

        Only used when the caller could not supply the real name. Takes the
        first label that identifies a repository rather than infrastructure, so
        'www.gesis.org' asks about 'gesis' and 'data.dtu.dk' about 'dtu'. Never
        steps onto the final label - that is the public suffix, not a name - and
        returns None rather than asking a question with no possible answer.
        """
        normalized = self._normalize_hostname(hostname)
        if not normalized:
            return None
        for label in normalized.split('.')[:-1]:
            if label not in GENERIC_HOST_LABELS:
                return label
        return None

    def harvest_by_id(self, fairsharing_id):
        """
        Harvests metadata directly from FAIRsharing using its DOI.
        """
        with self._serialized():
            if not self.jwt_token:
                raise RegistryUnavailableError(
                    'fairsharing',
                    "not signed in - check the FAIRSHARING_USERNAME and "
                    "FAIRSHARING_PASSWORD environment variables",
                )

            self.logger.info(f"-- Harvesting from FAIRsharing by ID: {fairsharing_id} --")
            return self._search_fairsharing(fairsharing_id, expected_doi=fairsharing_id)

    def _normalize_hostname(self, hostname):
        """
        Normalize a hostname by converting to lowercase and removing 'www.' prefix.
        """
        if not hostname:
            return None
        hostname = hostname.lower()
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname

    def _hostnames_match(self, query_hostname, record_hostname):
        """
        Check if two hostnames match, accounting for subdomains.

        Returns True if:
        - They are equal (after normalizing)
        - One is a direct subdomain of the other (depth difference of 1)

        This is more conservative than root-domain matching, which incorrectly matched
        any hosts under the same TLD (e.g., 'data.dans.knaw.nl' with 'other.knaw.nl').

        The depth check prevents matching deep subdomains with root domains:
        - 'about.coscine.de' (3 parts) matches 'coscine.de' (2 parts) - diff 1 ✓
        - 'data.dans.knaw.nl' (4 parts) does NOT match 'knaw.nl' (2 parts) - diff 2 ✗
        - 'data.dans.knaw.nl' (4 parts) matches 'dans.knaw.nl' (3 parts) - diff 1 ✓
        """
        h1 = self._normalize_hostname(query_hostname)
        h2 = self._normalize_hostname(record_hostname)

        if not h1 or not h2:
            return False

        if h1 == h2:
            return True

        # Check if one is a subdomain of the other with max depth difference of 1
        # e.g., "about.coscine.de" should match "coscine.de"
        h1_parts = h1.split('.')
        h2_parts = h2.split('.')
        depth_diff = abs(len(h1_parts) - len(h2_parts))

        if depth_diff == 1:
            if h1.endswith('.' + h2) or h2.endswith('.' + h1):
                return True

        return False

    def _post_search(self, query):
        """One search POST, with 429 backoff. Returns the response."""
        search_url = f"{self.api_url}/search/fairsharing_records/"
        auth_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.jwt_token}"
        }
        self.logger.info(f"Querying FAIRsharing API: {search_url} with query='{query}'")
        return request_with_backoff(
            self.session, 'POST', search_url, 'fairsharing',
            headers=auth_headers, data=json.dumps({"q": query}), timeout=15,
        )

    def _search_fairsharing(self, query, hostname_filter=None, expected_doi=None):
        """
        Helper to search FAIRsharing API and fetch details for the first match.
        """
        response = self._post_search(query)

        if response.status_code == 401:
            # One shared token covers a whole batch, so it may expire mid-run.
            # Sign in again once before treating this as a real auth failure.
            self.logger.info(
                "FAIRsharing rejected the token (401); re-authenticating once."
            )
            self._authenticate()
            if not self.jwt_token:
                raise RegistryUnavailableError(
                    'fairsharing', 'sign-in was rejected while renewing the session token'
                )
            response = self._post_search(query)

        if response.status_code == 401:
            raise RegistryUnavailableError(
                'fairsharing', 'HTTP 401 even after renewing the session token'
            )

        try:
            response.raise_for_status()
            results = response.json().get('data', [])
        except requests.exceptions.RequestException as e:
            raise RegistryUnavailableError(
                'fairsharing', f"search response could not be read: {e}"
            )
        self.logger.info(f"FAIRsharing API returned {len(results)} results.")
        return self._parse_search_results(results, hostname_filter, expected_doi)

    def _parse_search_results(self, results, hostname_filter=None, expected_doi=None):
        """
        Parses the FAIRsharing JSON search results to find the best match.
        """
        if not results:
            return None

        matching_records = []
        
        # If we have an expected DOI, filter strictly by that
        if expected_doi:
            self.logger.info(f"Filtering results for exact DOI match: {expected_doi}")
            for record in results:
                metadata_nested = record.get('attributes', {}).get('metadata', {})
                record_doi = metadata_nested.get('doi')
                # Case-insensitive comparison for DOIs
                if record_doi and expected_doi and record_doi.lower() == expected_doi.lower():
                    self.logger.info(f"Match found! Record DOI '{record_doi}' matches expected DOI.")
                    matching_records.append(record)
                    break  # Found exact match
                else:
                    # self.logger.debug(f"Skipping record with DOI '{record_doi}'")
                    pass
        
        # Otherwise, filter by hostname if provided
        elif hostname_filter:
            self.logger.info(f"Filtering results for hostname match: '{hostname_filter}'")

            for record in results:
                if record.get('type') != 'fairsharing_records':
                    continue

                homepage = record.get('attributes', {}).get('metadata', {}).get('homepage')
                if not homepage:
                    continue

                try:
                    record_hostname = urlparse(homepage).hostname
                    if record_hostname and self._hostnames_match(hostname_filter, record_hostname):
                        self.logger.info(f"Match found! Record homepage '{homepage}' matches query hostname '{hostname_filter}'.")
                        matching_records.append(record)
                except Exception:
                    continue
        
        if not matching_records:
            # If we were searching by ID and found nothing, return None
            if expected_doi:
                self.logger.warning(f"No FAIRsharing record found matching DOI: {expected_doi}")
                return None
            
            # If we were searching by hostname and found nothing
            if hostname_filter:
                self.logger.info(f"No records matched the hostname filter: {hostname_filter}")
                return None
                
            # Fallback (shouldn't be reached with current logic)
            return None

        best_record = None
        for record in matching_records:
            if record.get('attributes', {}).get('metadata', {}).get('status') == 'ready':
                best_record = record
                break
        if not best_record:
            for record in matching_records:
                if record.get('attributes', {}).get('metadata', {}).get('status') != 'deprecated':
                    best_record = record
                    break
        
        if not best_record:
            self.logger.info("Matching records found, but none were active/ready.")
            return None

        #metadata_nested = attributes.get('metadata', {})
        metadata = None
        try:
            metadata = jmespath.search(FAIRSHARING_QUERY, best_record)
            #print(json.dumps(metadata, indent=2))
        except Exception as e:
            self.logger.error(
                "Could not parse FAIRsharing record %s with JMESPATH: %s",
                best_record.get('id'), e,
            )
            return None

        '''metadata = {
            'fairsharingID': best_record.get('id'),
            'title': metadata_nested.get('name'),
            'description': metadata_nested.get('description'),
            'landingPage': metadata_nested.get('homepage'),
            'identifier': [metadata_nested.get('doi')] if metadata_nested.get('doi') else None
        }'''
        
        return {k: v for k, v in metadata.items() if v}
