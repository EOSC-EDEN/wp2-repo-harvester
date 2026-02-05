import os
import json

import jmespath
import requests
from urllib.parse import urlparse
import logging
from repo_harvester_server.helper.JMESPATHQueries import FAIRSHARING_QUERY
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

class FAIRsharingHarvester:
    """
    A harvester for fetching metadata from the FAIRsharing.org registry.
    Handles authentication and searching for repository records.
    """
    logger = logging.getLogger('FAIRsharingHarvester')

    def __init__(self):
        self.api_url = "https://api.fairsharing.org"
        self.jwt_token = None
        self._authenticate()

    def _authenticate(self):
        """
        Authenticates with the FAIRsharing API using environment variables.
        """
        username = os.environ.get('FAIRSHARING_USERNAME')
        password = os.environ.get('FAIRSHARING_PASSWORD')

        if not username or not password:
            self.logger.warning("FAIRSHARING_USERNAME and/or FAIRSHARING_PASSWORD environment variables not set. Authentication will fail.")
            return

        url = f"{self.api_url}/users/sign_in"
        payload = {"user": {"login": username, "password": password}}
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status()
            data = response.json()
            self.jwt_token = data.get('jwt')
            if self.jwt_token:
                self.logger.info("Successfully authenticated with FAIRsharing.")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to authenticate with FAIRsharing: {e}")

    def harvest(self, catalog_url):
        """
        Public method to harvest metadata for a given URL.
        """
        if not self.jwt_token:
            self.logger.warning("Skipping FAIRsharing harvesting due to authentication failure.")
            return None

        self.logger.info("Harvesting from FAIRsharing...")
        hostname = urlparse(catalog_url).hostname
        if not hostname:
            return None

        # Strategy 1: Search by hostname
        self.logger.info(f"Strategy 1: Searching FAIRsharing by hostname: '{hostname}'")
        metadata = self._search_fairsharing(hostname, hostname_filter=hostname)
        if metadata:
            self.logger.info(f"Found FAIRsharing record via hostname search: {metadata.get('title')}")
            return metadata

        # Strategy 2: Search by repository name
        repo_name = hostname.split('.')[0]
        if repo_name != hostname:
            self.logger.info(f"Strategy 2: Retrying FAIRsharing search with repository name: '{repo_name}'")
            metadata = self._search_fairsharing(repo_name, hostname_filter=hostname)
            if metadata:
                self.logger.info(f"Found FAIRsharing record via name search: {metadata.get('title')}")
                return metadata

        self.logger.info("FAIRsharing harvest failed: No matching records found.")
        return None

    def harvest_by_id(self, fairsharing_id):
        """
        Harvests metadata directly from FAIRsharing using its DOI.
        """
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

    def _search_fairsharing(self, query, hostname_filter=None, expected_doi=None):
        """
        Helper to search FAIRsharing API and fetch details for the first match.
        """
        search_url = f"{self.api_url}/search/fairsharing_records/"
        payload = {"q": query}
        auth_headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.jwt_token}"
        }

        try:
            self.logger.info(f"Querying FAIRsharing API: {search_url} with query='{query}'")
            response = requests.post(search_url, headers=auth_headers, data=json.dumps(payload), timeout=15)
            if response.status_code == 401:
                self.logger.warning("FAIRsharing search failed: 401 Unauthorized. Check permissions.")
                return None
            response.raise_for_status()
            
            results = response.json().get('data', [])
            self.logger.info(f"FAIRsharing API returned {len(results)} results.")
            return self._parse_search_results(results, hostname_filter, expected_doi)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error querying FAIRsharing search API: {e}")
        return None

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

        attributes = best_record.get('attributes', {})
        #metadata_nested = attributes.get('metadata', {})
        try:
            metadata = jmespath.search(FAIRSHARING_QUERY, best_record)
            #print(json.dumps(metadata, indent=2))
        except Exception as e:
            self.logger.warning(f"Error parsing FAIRsharing search results with JMESPATH : {e}")

        '''metadata = {
            'fairsharingID': best_record.get('id'),
            'title': metadata_nested.get('name'),
            'description': metadata_nested.get('description'),
            'landingPage': metadata_nested.get('homepage'),
            'identifier': [metadata_nested.get('doi')] if metadata_nested.get('doi') else None
        }'''
        
        return {k: v for k, v in metadata.items() if v}
