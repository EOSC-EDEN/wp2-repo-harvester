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
        Authenticates with the FAIRsharing API using credentials from
        environment variables to get a JWT for subsequent requests.
        """
        username = os.environ.get('FAIRSHARING_USERNAME')
        password = os.environ.get('FAIRSHARING_PASSWORD')

        if not username or not password:
            self.logger.warning("FAIRsharing credentials (FAIRSHARING_USERNAME, FAIRSHARING_PASSWORD) not found in environment variables. Skipping authentication.")
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
                print("Successfully authenticated with FAIRsharing.")
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

        domain_parts = hostname.split('.')
        search_query = domain_parts[-2] if len(domain_parts) > 1 else domain_parts[0]

        search_url = f"{self.api_url}/search/fairsharing_records/"
        payload = {"q": search_query}
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
            # print(f"RAW FAIRsharing API results: {json.dumps(results, indent=4)}")
            return self._parse_search_results(results, hostname)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error querying FAIRsharing search API: {e}")
        return None

    def _parse_search_results(self, results, hostname):
        """
        Parses the FAIRsharing JSON search results to find the best match.
        """
        print(f"FAIRsharing API returned {len(results)} results.")
        matching_records = []
        normalized_hostname = hostname.lower().replace('www.', '', 1)
        
        for i, record in enumerate(results):
            self.logger.info(f"--- Processing record {i} ---")
            # print(f"Record keys: {record.keys()}")
            
            if record.get('type') != 'fairsharing_records': # Changed from 'database' to 'fairsharing_records' based on raw output
                # print(f"Skipping record type: {record.get('type')}")
                # continue # Don't skip yet, let's see what's inside
                pass

            attributes = record.get('attributes', {})
            # print(f"Attributes keys: {attributes.keys()}")
            
            metadata_nested = attributes.get('metadata', {})
            # print(f"Metadata keys: {metadata_nested.keys()}")
            
            homepage = metadata_nested.get('homepage')
            print(f"  - Name: {metadata_nested.get('name')}")
            print(f"  - Homepage: {homepage}")
            
            if not homepage:
                print("  - Skipping: No homepage found.")
                continue

            try:
                record_hostname = urlparse(homepage).hostname
                if record_hostname:
                    normalized_record_hostname = record_hostname.lower().replace('www.', '', 1)
                    print(f"    Comparing '{normalized_record_hostname}' with '{normalized_hostname}'")
                    if normalized_record_hostname == normalized_hostname:
                        print(f"    -> Found a match!")
                        matching_records.append(record)
            except Exception as e:
                print(f"Error parsing URL: {e}")
                continue
        
        if not matching_records:
            print("No matching records found after filtering.")
            return None

        best_record = None
        for record in matching_records:
            # Check status in nested metadata
            if record.get('attributes', {}).get('metadata', {}).get('status') == 'ready':
                best_record = record
                break
        if not best_record:
            for record in matching_records:
                if record.get('attributes', {}).get('metadata', {}).get('status') != 'deprecated':
                    best_record = record
                    break
        
        if not best_record:
            print(f"Found {len(matching_records)} match(es) on FAIRsharing for {hostname}, but none were active.")
            return None

        attributes = best_record.get('attributes', {})
        metadata_nested = attributes.get('metadata', {})
        
        metadata = {
            'fairsharingID': best_record.get('id'),
            'title': metadata_nested.get('name'),
            'description': metadata_nested.get('description'),
            'landingPage': metadata_nested.get('homepage'),
        }
        
        return {k: v for k, v in metadata.items() if v}
