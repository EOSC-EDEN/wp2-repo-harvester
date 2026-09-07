import json
import re

import requests
from urllib.parse import urlparse

from repo_harvester_server.helper import UrlMatching
from lxml import etree
import os
import csv
import logging
from repo_harvester_server.data.country_codes import country_codes_3
from repo_harvester_server.helper.ServiceInfoHelper import ServiceInfoHelper
from repo_harvester_server.helper.RegistryHTTP import (
    RegistryUnavailableError,
    request_with_backoff,
)


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
class Re3DataHarvester:
    """
    A harvester for fetching metadata from the re3data.org registry.
    """
    logger = logging.getLogger('Re3DataHarvester')

    def __init__(self):
        self.api_url = "https://www.re3data.org/api/beta"
        self.ns = {"r3d": "http://www.re3data.org/schema/2-2"}
        # One session for the search plus every record fetch it triggers:
        # re3data is our heaviest caller, so connection reuse matters most here.
        self.session = requests.Session()
        self.service_helper = ServiceInfoHelper()

        #self.service_mappings = self._load_service_mappings()

    '''def _load_service_mappings(self):
        """Loads the service mappings from the CSV file."""
        mappings = {}
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'services_default_queries.csv')
        try:
            with open(csv_path, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                for row in reader:
                    if row['Acronym']:
                        mappings[row['Acronym']] = row['URI']
        except FileNotFoundError:
            self.logger.warning(f"Warning: Service mapping file not found at {csv_path}")
        return mappings'''

    def harvest(self, catalog_url, repository_name=None):
        """Find the re3data record for one or more repository URLs."""
        self.logger.info("-- Harvesting from re3data by URL -- ")
        catalog_urls = [url.strip() for url in catalog_url.split('|') if url.strip()]
        candidates = self._search_candidates_for_queries(catalog_urls)
        records = self._fetch_candidate_records(candidates)
        exact_matches = [
            record for record in records
            if any(
                self._urls_match(record['url'], url)
                for url in catalog_urls
            )
        ]
        exact_match = self._best_named_match(
            exact_matches, repository_name, catalog_urls
        )
        if exact_match:
            return self._parse_record(exact_match['root'])

        # A full URL search may miss other repositories on the same host.
        # Search the hostname too before accepting a less exact match.
        hostnames = list(dict.fromkeys(
            hostname
            for hostname in (urlparse(url).hostname for url in catalog_urls)
            if hostname
        ))
        hostname_candidates = self._search_candidates_for_queries(hostnames)
        known_ids = {candidate['id'] for candidate in candidates}
        new_candidates = [
            candidate for candidate in hostname_candidates
            if candidate['id'] not in known_ids
        ]
        candidates.extend(new_candidates)
        records.extend(self._fetch_candidate_records(new_candidates))
        url_search_records = list(records)

        exact_matches = [
            record for record in records
            if any(
                self._urls_match(record['url'], url)
                for url in catalog_urls
            )
        ]
        exact_match = self._best_named_match(
            exact_matches, repository_name, catalog_urls
        )
        if exact_match:
            return self._parse_record(exact_match['root'])

        related_records = []
        best_related_records = []
        if repository_name:
            related_records = [
                record for record in records
                if self._url_score(catalog_urls, record['url']) > 0
                and self._name_score(repository_name, record['name']) > 0
            ]
            related_match = self._best_named_match(
                related_records, repository_name, catalog_urls
            )
            if related_match:
                return self._parse_record(related_match['root'])

            name_candidates = self._search_candidates_for_queries([repository_name])
            known_ids = {candidate['id'] for candidate in candidates}
            new_candidates = [
                candidate for candidate in name_candidates
                if candidate['id'] not in known_ids
            ]
            candidates.extend(new_candidates)
            records.extend(self._fetch_candidate_records(new_candidates))
            exact_matches = [
                record for record in records
                if any(
                    self._urls_match(record['url'], url)
                    for url in catalog_urls
                )
            ]
            exact_match = self._best_named_match(
                exact_matches, repository_name, catalog_urls
            )
            if exact_match:
                return self._parse_record(exact_match['root'])

            related_records = [
                record for record in records
                if self._url_score(catalog_urls, record['url']) > 0
                and self._name_score(repository_name, record['name']) > 0
            ]
            related_match = self._best_named_match(
                related_records, repository_name, catalog_urls, require_name=True
            )
            if related_match:
                return self._parse_record(related_match['root'])
            best_related_records = self._best_named_records(
                related_records, repository_name, catalog_urls
            )

        strong_ambiguities = []
        for matches in (exact_matches, best_related_records):
            if len(matches) > 1:
                strong_ambiguities.extend(matches)
        if strong_ambiguities:
            self._log_ambiguous_match(catalog_urls, strong_ambiguities)
            return None

        url_search_matches = [
            record for record in url_search_records
            if self._url_score(catalog_urls, record['url']) > 0
        ]
        all_url_matches = [
            record for record in records
            if self._url_score(catalog_urls, record['url']) > 0
        ]
        if len(url_search_matches) == 1 and len(all_url_matches) == 1:
            return self._parse_record(url_search_matches[0]['root'])

        best_name_records = self._best_named_records(
            records, repository_name, catalog_urls
        )
        remaining_ambiguities = []
        for matches in (all_url_matches, best_name_records):
            if len(matches) > 1:
                remaining_ambiguities.extend(matches)
        if remaining_ambiguities:
            self._log_ambiguous_match(catalog_urls, remaining_ambiguities)

        self.logger.info("re3data has no matching entry for URLs: %s", catalog_urls)
        return None

    def _normalize_url(self, url):
        """Prepare a URL for comparison without losing its path or parameters."""
        return UrlMatching.normalize_url(url)

    def _urls_match(self, first_url, second_url):
        """Check whether two URLs point to the same repository."""
        return UrlMatching.urls_match(first_url, second_url)

    def _name_score(self, expected_name, candidate_name):
        """Score how closely two repository names match.

        3: The names are the same after lowercasing and removing punctuation.
        2: After ignoring common words such as "data" and "repository", one
           name has at least two words and all of them appear in the other.
        1: A capitalized abbreviation of at least three characters from the
           expected name appears as a word in the result name.
        0: There is no reliable name match.

        The name score is compared first. The URL score only breaks a tie
        between records with the same name score.
        """
        if not expected_name or not candidate_name:
            return 0

        def normalize(value):
            """Lowercase a name and keep only its words."""
            return ' '.join(re.findall(r'[^\W_]+', value.casefold()))

        expected = normalize(expected_name)
        candidate = normalize(candidate_name)
        if expected == candidate:
            return 3

        generic = {
            'and', 'archive', 'archives', 'center', 'centre', 'data',
            'database', 'for', 'institute', 'institution', 'of',
            'repository', 'service', 'services', 'station', 'the',
        }
        expected_tokens = set(expected.split())
        candidate_tokens = set(candidate.split())
        expected_distinctive = expected_tokens - generic
        candidate_distinctive = candidate_tokens - generic
        if (
            len(expected_distinctive) >= 2
            and expected_distinctive <= candidate_tokens
        ) or (
            len(candidate_distinctive) >= 2
            and candidate_distinctive <= expected_tokens
        ):
            return 2

        expected_acronyms = {
            token.casefold()
            for token in re.findall(r'[A-Za-z0-9]+', expected_name)
            if len(token) >= 3 and token.isupper()
        }
        if expected_acronyms & candidate_tokens:
            return 1
        return 0

    def _url_score(self, catalog_urls, candidate_url):
        """Score how closely a result URL matches the submitted URLs."""
        return UrlMatching.url_score(
            catalog_urls, candidate_url, host_matcher=self._hostnames_match
        )

    def _best_named_match(
        self, records, repository_name, catalog_urls, require_name=False
    ):
        """Return the best match, or None when there is no clear winner."""
        if not records:
            return None
        if len(records) == 1 and not require_name:
            return records[0]
        best_records = self._best_named_records(
            records, repository_name, catalog_urls
        )
        return best_records[0] if len(best_records) == 1 else None

    def _best_named_records(self, records, repository_name, catalog_urls):
        """Return the records with the best name and URL score."""
        if not records or not repository_name:
            return []

        scored = [
            (
                self._name_score(repository_name, record['name']),
                self._url_score(catalog_urls, record['url']),
                record,
            )
            for record in records
        ]
        best_score = max(
            (name_score, url_score)
            for name_score, url_score, _ in scored
        )
        if best_score[0] == 0:
            return []
        return [
            record for name_score, url_score, record in scored
            if (name_score, url_score) == best_score
        ]

    def _search_candidates_for_queries(self, queries):
        """Search re3data for each query and remove duplicate results."""
        candidates = []
        seen_ids = set()
        for query in queries:
            for candidate in self._search_candidates(query):
                if candidate['id'] not in seen_ids:
                    seen_ids.add(candidate['id'])
                    candidates.append(candidate)
        return candidates

    def _search_candidates(self, query):
        """Search re3data once and return each result's ID and name."""
        search_url = f"{self.api_url}/repositories"
        self.logger.info("Searching re3data for: %s", query)
        resp = request_with_backoff(
            self.session, 'GET', search_url, 're3data',
            timeout=15, params={'query': query},
        )
        try:
            resp.raise_for_status()
            root = etree.fromstring(resp.content)
        except (requests.exceptions.RequestException, etree.XMLSyntaxError) as e:
            raise RegistryUnavailableError(
                're3data', f"search response could not be read: {e}"
            )

        candidates = []
        for repo_element in root.findall('.//repository'):
            repo_id_elem = repo_element.find('id')
            repo_name_elem = repo_element.find('name')
            if repo_id_elem is None or not repo_id_elem.text:
                self.logger.warning("Found a search result with no ID, skipping.")
                continue
            candidates.append({
                'id': repo_id_elem.text,
                'name': repo_name_elem.text if repo_name_elem is not None else None,
            })
        return candidates

    def _fetch_candidate_records(self, candidates):
        """Load full records that include a repository URL."""
        records = []
        for candidate in candidates:
            repo_root = self._fetch_and_parse_record_xml(candidate['id'])
            if repo_root is None:
                continue
            url_element = repo_root.find('.//r3d:repositoryURL', self.ns)
            if url_element is None or not url_element.text:
                continue
            records.append({
                'id': candidate['id'],
                'name': self._record_name(repo_root) or candidate['name'],
                'url': url_element.text.strip(),
                'root': repo_root,
            })
        return records

    def _record_name(self, repo_root):
        """Read the repository name from a full re3data record."""
        name_element = repo_root.find('.//r3d:repositoryName', self.ns)
        if name_element is not None and name_element.text:
            return name_element.text.strip()
        return None

    def _log_ambiguous_match(self, catalog_urls, records):
        """Log the IDs when more than one record could be correct."""
        candidate_ids = list(dict.fromkeys(record['id'] for record in records))
        self.logger.warning(
            "More than one re3data record matches %s; record IDs: %s",
            catalog_urls,
            candidate_ids,
        )

    def harvest_by_name(self, repo_name):
        """
        Public method to harvest metadata by repository name.
        """
        self.logger.info(f"-- Harvesting from re3data by Name: {repo_name} --")
        return self._search_and_verify(repo_name, 'name')

    def _normalize_hostname(self, hostname):
        """Normalize a hostname: lowercase, and drop a leading 'www.'."""
        return UrlMatching.normalize_hostname(hostname)

    def _hostnames_match(self, query_hostname, record_hostname):
        """Check if two hostnames match, accounting for subdomains.

        query_hostname may carry several alternatives joined by '|' (the form
        _search_and_verify passes through from the caller's catalog_ids); any
        one of them matching is a match.
        """
        return any(
            UrlMatching.hostnames_match(alternative, record_hostname)
            for alternative in str(query_hostname).split('|')
        )

    def _search_and_verify(self, query, search_type):
        search_url = f"{self.api_url}/repositories?query={query}"
        self.logger.info(f"Querying re3data search API: {search_url}")
        resp = request_with_backoff(self.session, 'GET', search_url, 're3data', timeout=15)
        try:
            resp.raise_for_status()
            root = etree.fromstring(resp.content)
        except (requests.exceptions.RequestException, etree.XMLSyntaxError) as e:
            # An unreadable answer is no answer: report it rather than
            # recording a miss the repository does not deserve.
            raise RegistryUnavailableError(
                're3data', f"search response could not be read: {e}"
            )

        # Iterate through <repository> elements in the search result list
        for repo_element in root.findall('.//repository'):
            repo_id_elem = repo_element.find('id')
            repo_name_elem = repo_element.find('name')

            if repo_id_elem is None or not repo_id_elem.text:
                self.logger.warning("Found a search result with no ID, skipping.")
                continue

            repo_id = repo_id_elem.text

            # Verification logic based on search type
            if search_type == 'name':
                if repo_name_elem is not None and repo_name_elem.text:
                    self.logger.info(f"Verifying name match for ID {repo_id}: Query='{query}', Found='{repo_name_elem.text}'")
                    if query.lower() in repo_name_elem.text.lower():
                        self.logger.info(f"SUCCESS: Found verified re3data entry for '{query}' via name search: {repo_id}")
                        return self.harvest_by_id(repo_id)

            elif search_type == 'hostname':
                # For hostname verification, we still need to fetch the full record to get the URL
                # because the search result list doesn't include the repositoryURL.
                repo_root = self._fetch_and_parse_record_xml(repo_id)
                if repo_root is None:
                    continue

                repo_main_url_element = repo_root.find('.//r3d:repositoryURL', self.ns)
                if repo_main_url_element is not None and repo_main_url_element.text:
                    re3data_hostname = urlparse(repo_main_url_element.text).hostname

                    self.logger.info(f"Verifying hostname match for ID {repo_id}: Query='{query}', Found='{re3data_hostname}'")

                    if self._hostnames_match(query, re3data_hostname):
                        self.logger.info(f"SUCCESS: Found verified re3data entry for '{query}' via hostname search: {repo_id}")
                        return self._parse_record(repo_root)

        self.logger.info(f"re3data has no verified entry for query: '{query}'")
        return None

    def harvest_by_id(self, re3data_id):
        """
        Harvests metadata directly from re3data using its re3data.orgIdentifier.
        """
        self.logger.info(f"-- Harvesting from re3data by ID: {re3data_id} --")
        repo_root = self._fetch_and_parse_record_xml(re3data_id)
        if repo_root is not None:
            self.logger.info(f"Successfully fetched re3data entry for ID: {re3data_id}")
            return self._parse_record(repo_root)
        return None

    def _fetch_and_parse_record_xml(self, repo_id):
        """
        Helper method to fetch and parse the detailed XML record for a given repo_id.

        Rate limiting propagates (there is no point walking the remaining search
        hits while re3data is refusing us), and so does a 5xx: the registry is
        not answering, not telling us the record is absent, so this must not be
        recorded as a genuine miss for `harvest_by_id`'s single-record callers.
        A 404 or an unparseable body is a genuinely absent/unreadable record
        (e.g. a stale bridged ID) and stays a plain `None` so the hostname-search
        loop skips just this one candidate and keeps going.
        """
        repo_url = f"{self.api_url}/repository/{repo_id}"
        repo_resp = request_with_backoff(
            self.session, 'GET', repo_url, 're3data', timeout=15
        )
        if repo_resp.status_code >= 500:
            raise RegistryUnavailableError(
                're3data',
                f"record fetch for {repo_id} failed: HTTP {repo_resp.status_code}",
            )
        try:
            repo_resp.raise_for_status()
            return etree.fromstring(repo_resp.content)
        except (requests.exceptions.RequestException, etree.XMLSyntaxError) as e:
            self.logger.error(f"Failed to fetch or parse record for re3data ID {repo_id}: {e}")
            return None

    def _parse_record(self, repo_root):
        """
        Parses the detailed XML for a specific repository from re3data.
        """
        # General purpose helper for single-value text fields
        def find_text(element, path):
            node = element.find(path, self.ns)
            return node.text.strip() if node is not None and node.text else None

        # General purpose helper for multi-value text fields
        def find_all_text(element, path):
            return [node.text.strip() for node in element.findall(path, self.ns) if node.text]
        #TODO: license missing!!

        # --- Publisher / Institution Extraction (Handles Multiple) ---
        publishers = []
        for inst_element in repo_root.findall(".//r3d:institution", self.ns):
            inst_name = find_text(inst_element, 'r3d:institutionName')
            inst_country = find_text(inst_element, 'r3d:institutionCountry')
            inst_url = find_text(inst_element, 'r3d:institutionURL')
            if re.match(r'^[A-Z]{3}$', str(inst_country)):
                if inst_country in country_codes_3:
                    inst_country = country_codes_3[inst_country]
            if inst_name:
                publishers.append({"type": "org:Organization", "name": inst_name, "country": inst_country, "url": inst_url})
        contact = {}
        for contact_elem in repo_root.findall(".//r3d:repositoryContact", self.ns):
            if '@' in contact_elem.text:
                contact['email'] = contact_elem.text
            elif 'http' in contact_elem.text:
                contact['url'] = contact_elem.text
        # --- Service Extraction (Handles Multiple) ---
        services = []
        for api_elem in repo_root.findall(".//r3d:api", self.ns):
            api_type = api_elem.get('apiType')
            api_url = api_elem.text.strip() if api_elem.text else None
            if api_url:
                services.append({
                    'endpoint_uri': api_url,
                    #'title': f"re3data:API:{api_type}",
                    'conforms_to': self.service_helper.conforms_to(api_type),
                    'type': self.service_helper.type(api_type)
                    #'title': f"{api_type} API" if api_type else "API Service"
                })
        for syndication_elem in repo_root.findall(".//r3d:syndication", self.ns):
            syndication_type = syndication_elem.get('syndicationType')
            syndication_url = syndication_elem.text.strip() if syndication_elem.text else None
            if syndication_url:
                services.append({
                    'endpoint_uri': syndication_url,
                    #'title': f"re3data:Syndication:{syndication_type}",
                    'conforms_to': self.service_helper.conforms_to(syndication_type),
                    'type': self.service_helper.type(syndication_type),
                    #'conforms_to': self.service_mappings.get(syndication_type),
                    #'title': f"{syndication_type}" if syndication_type else "Feed"
                })
        
        # --- Identifier Extraction (Handles Multiple) ---
        identifiers = [
            find_text(repo_root, ".//r3d:re3data.orgIdentifier"),
            find_text(repo_root, ".//r3d:repositoryURL")
        ] + find_all_text(repo_root, ".//r3d:repositoryIdentifier")

        policies = []
        for policy_elem in repo_root.findall(".//r3d:policy", self.ns):
            policy_name =  find_text(policy_elem, 'r3d:policyName')
            policy_url = find_text(policy_elem, 'r3d:policyURL')
            policies.append({'policy_uri':policy_url, 'title': policy_name})

        keywords = find_all_text(repo_root, ".//r3d:keyword")
        keywords.extend(find_all_text(repo_root, ".//r3d:subject"))
        clean_keywords = []
        for kw in keywords:
            #clean DFG style subjects
            clean_keywords.append(re.sub(r'^([0-9]+\s)', '', kw, flags=re.M))
        keywords = clean_keywords

        metadata = {
            'resource_type' : 'r3d:Repository',# see: https://github.com/re3data/ontology/blob/master/r3dOntology.ttl
            'title': find_text(repo_root, ".//r3d:repositoryName"),
            'description': find_text(repo_root, ".//r3d:description"),
            'identifier': [i for i in identifiers if i],
            'publisher': publishers if publishers else None,
            'contact' : contact,
            #'contact': find_all_text(repo_root, ".//r3d:repositoryContact"),
            'services': services if services else None,
            'policies': policies if policies else None,
            'keywords': find_all_text(repo_root, ".//r3d:keyword"),
            'subject': keywords if keywords else None,
            'license': find_text(repo_root, ".//r3d:dataLicenseURL") or find_text(repo_root, ".//r3d:dataLicenseName"),
        }
        return {k: v for k, v in metadata.items() if v}
