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
        metadata = self._search_fairsharing(hostname)
        if metadata:
            return metadata

        # Strategy 2: Search by repository name
        repo_name = hostname.split('.')[0]
        if repo_name != hostname:
            self.logger.info(f"Retrying FAIRsharing search with repository name: {repo_name}")
            metadata = self._search_fairsharing(repo_name)
            if metadata:
                return metadata

        return None

    def harvest_by_id(self, fairsharing_id):
        """
        Harvests metadata directly from FAIRsharing using its DOI.
        """
        self.logger.info(f"-- Harvesting from FAIRsharing by ID: {fairsharing_id} --")
        return self._search_fairsharing(fairsharing_id)

    def _search_fairsharing(self, query):
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
            # Since we might be searching by URL or by ID, we don't have a single hostname to verify against.
            # We will just take the first valid result.
            return self._parse_search_results(results)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error querying FAIRsharing search API: {e}")
        return None

    def _parse_search_results(self, results):
        """
        Parses the FAIRsharing JSON search results to find the best match.
        """
        if not results:
            return None

        # For now, we assume the first result is the best one, especially when searching by ID.
        best_record = results[0]
        
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
