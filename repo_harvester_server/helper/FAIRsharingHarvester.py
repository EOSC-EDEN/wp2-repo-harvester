import os
import json
import requests
from urllib.parse import urlparse
import logging
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
        Authenticates with the FAIRsharing API. It first tries environment
        variables, then falls back to a local credentials file.
        """
        username = os.environ.get('FAIRSHARING_USERNAME')
        password = os.environ.get('FAIRSHARING_PASSWORD')

        if not username or not password:
            self.logger.info("FAIRsharing credentials not in environment variables. Trying local file...")
            try:
                cred_path = os.path.join(os.path.dirname(__file__), 'fairsharing_credentials.json')
                with open(cred_path, 'r') as f:
                    creds = json.load(f)
                    username = creds.get('FAIRSHARING_USERNAME')
                    password = creds.get('FAIRSHARING_PASSWORD')
            except FileNotFoundError:
                self.logger.warning("Local credentials file 'fairsharing_credentials.json' not found.")
                return
            except (json.JSONDecodeError, KeyError):
                self.logger.warning("Error reading local credentials file. Make sure it is valid JSON with the correct keys.")
                return

        if not username or not password:
            self.logger.warning("FAIRsharing credentials could not be loaded.")
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
        metadata = self._search_fairsharing(hostname, hostname_filter=hostname)
        if metadata:
            return metadata

        # Strategy 2: Search by repository name
        repo_name = hostname.split('.')[0]
        if repo_name != hostname:
            self.logger.info(f"Retrying FAIRsharing search with repository name: {repo_name}")
            metadata = self._search_fairsharing(repo_name, hostname_filter=hostname)
            if metadata:
                return metadata

        return None

    def harvest_by_id(self, fairsharing_id):
        """
        Harvests metadata directly from FAIRsharing using its DOI.
        """
        self.logger.info(f"-- Harvesting from FAIRsharing by ID: {fairsharing_id} --")
        return self._search_fairsharing(fairsharing_id, expected_doi=fairsharing_id)

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
            response = requests.post(search_url, headers=auth_headers, data=json.dumps(payload), timeout=15)
            if response.status_code == 401:
                self.logger.warning("FAIRsharing search failed: 401 Unauthorized. Check permissions.")
                return None
            response.raise_for_status()
            
            results = response.json().get('data', [])
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
            for record in results:
                metadata_nested = record.get('attributes', {}).get('metadata', {})
                if metadata_nested.get('doi') == expected_doi:
                    matching_records.append(record)
                    break # Found exact match
        
        # Otherwise, filter by hostname if provided
        elif hostname_filter:
            normalized_hostname = hostname_filter.lower().replace('www.', '', 1)
            for record in results:
                if record.get('type') != 'fairsharing_records':
                    continue

                homepage = record.get('attributes', {}).get('metadata', {}).get('homepage')
                if not homepage:
                    continue

                try:
                    record_hostname = urlparse(homepage).hostname
                    if record_hostname:
                        normalized_record_hostname = record_hostname.lower().replace('www.', '', 1)
                        if normalized_record_hostname == normalized_hostname:
                            matching_records.append(record)
                except Exception:
                    continue
        
        # If no filters were applied (or no matches found yet), just take the first result?
        # No, that's dangerous. If we had filters and found nothing, we should return None.
        # If we had NO filters (which shouldn't happen with current logic), we might take the first.
        
        if not matching_records:
            # If we were searching by ID and found nothing, return None
            if expected_doi:
                self.logger.warning(f"No FAIRsharing record found matching DOI: {expected_doi}")
                return None
            
            # If we were searching by hostname and found nothing
            if hostname_filter:
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
            return None

        attributes = best_record.get('attributes', {})
        metadata_nested = attributes.get('metadata', {})
        
        metadata = {
            'fairsharingID': best_record.get('id'),
            'title': metadata_nested.get('name'),
            'description': metadata_nested.get('description'),
            'landingPage': metadata_nested.get('homepage'),
            'identifier': [metadata_nested.get('doi')] if metadata_nested.get('doi') else None
        }
        
        return {k: v for k, v in metadata.items() if v}
