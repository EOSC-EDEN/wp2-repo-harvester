import requests
import ftplib
from urllib.parse import urlparse
import os
import csv

class EndpointValidator:
    def __init__(self, timeout=10):
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'ResearchMetadataHarvester/1.0'
        }
        self.protocol_configs = self._load_service_mappings()

    def _load_service_mappings(self):
        """Loads the service mappings from the CSV file."""
        mappings = {}
        # Assuming the CSV is in the parent directory of this helper file
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'services_default_queries.csv')
        try:
            with open(csv_path, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                for row in reader:
                    if row['Acronym']:
                        # We store the whole row config, not just the URI
                        mappings[row['Acronym']] = {
                            'suffix': row['default query'] if row['default query'] else '',
                            'accept': row['accept'] if row['accept'] else '' # Ensure it's a string
                        }
        except FileNotFoundError:
            print(f"Warning: Service mapping file not found at {csv_path}")
        return mappings

    def validate_url(self, url, api_type):
        if not url:
            return {"valid": False, "error": "Empty URL"}

        api_type = api_type.strip()
        
        # Handle FTP separately
        if api_type.upper() == 'FTP' or url.startswith('ftp://'):
            return self._check_ftp(url)

        # Get configuration for this API type
        config = self.protocol_configs.get(api_type)

        if config:
            return self._check_specific_http(url, config)
        else:
            # Fallback for types not in the specific list
            return self._check_generic_http(url)

    def _check_specific_http(self, url, config):
        """
        Handles validation using the extracted default queries.
        """
        suffix = config['suffix']
        
        # Replace placeholder if present
        if suffix and '{endpointURI}' in suffix:
             suffix = suffix.replace('{endpointURI}', '')

        # Construct target URL
        if suffix:
            if suffix.startswith('?'):
                separator = '&' if '?' in url else '?'
                target_url = f"{url}{separator}{suffix.lstrip('?')}"
            elif suffix.startswith('/'):
                target_url = f"{url.rstrip('/')}{suffix}"
            else:
                # If suffix doesn't start with / or ?, just append it
                target_url = f"{url.rstrip('/')}/{suffix.lstrip('/')}"
        else:
            # If suffix is empty (or became empty after replacement), do NOT append a slash.
            target_url = url

        # Prepare headers
        req_headers = self.headers.copy()
        if config.get('accept'):
            req_headers['Accept'] = config['accept']

        try:
            response = requests.get(target_url, headers=req_headers, timeout=self.timeout)
            
            # Special handling for SPARQL (400 is often a success signal for missing query)
            if 'SPARQL' in (config.get('accept') or '') and response.status_code == 400:
                return {
                    "valid": True, 
                    "status_code": 400, 
                    "note": "Active (Missing Query params)", 
                    "url": target_url
                }

            is_valid = 200 <= response.status_code < 400
            return {
                "valid": is_valid,
                "status_code": response.status_code,
                "content_type": response.headers.get('Content-Type', 'unknown'),
                "url": target_url
            }
        except requests.RequestException as e:
            return {"valid": False, "error": str(e), "url": target_url}

    def _check_generic_http(self, url):
        """
        Standard GET for types without specific path requirements.
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            return {
                "valid": 200 <= response.status_code < 400,
                "status_code": response.status_code,
                "url": url
            }
        except requests.RequestException as e:
            return {"valid": False, "error": str(e), "url": url}

    def _check_ftp(self, url):
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port if parsed.port else 21
        
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=self.timeout)
            ftp.login()
            ftp.quit()
            return {"valid": True, "status_code": "OK"}
        except Exception as e:
            return {"valid": False, "error": str(e)}
