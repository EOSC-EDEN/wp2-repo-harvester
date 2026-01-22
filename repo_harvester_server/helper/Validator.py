import requests
import ftplib
from urllib.parse import urlparse, urljoin
import os
import csv
from lxml import html
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

class ServiceValidator:
    logger = logging.getLogger('ServiceValidator')

    def __init__(self, timeout=10):
        self.timeout = timeout
        self.headers = {
            'User-Agent': 'EDENHarvester/1.0'
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
            self.logger.warning(f"Warning: Service mapping file not found at {csv_path}")
        return mappings

    def validate_url(self, url, api_type, is_recovery_attempt=False):
        if not url:
            return {"valid": False, "error": "Empty URL"}

        api_type = api_type.strip()
        
        # Handle FTP separately
        if api_type.upper() == 'FTP' or url.startswith('ftp://'):
            return self._check_ftp(url)

        # Get configuration for this API type
        config = self.protocol_configs.get(api_type)

        if config:
            return self._check_specific_http(url, config, api_type, is_recovery_attempt)
        else:
            # Fallback for types not in the specific list
            return self._check_generic_http(url)

    def _check_specific_http(self, url, config, api_type, is_recovery_attempt):
        """
        Handles validation using the extracted default queries.
        """
        suffix = config['suffix']
        expected_mime = config['accept']
        
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
        if expected_mime:
            req_headers['Accept'] = expected_mime

        try:
            response = requests.get(target_url, headers=req_headers, timeout=self.timeout)
            
            # Special handling for SPARQL (400 is often a success signal for missing query)
            if 'SPARQL' in (expected_mime or '') and response.status_code == 400:
                return {
                    "valid": True, 
                    "status_code": 400, 
                    "note": "Active (Missing Query params)", 
                    "url": target_url
                }

            is_valid = 200 <= response.status_code < 400
            
            # Content-Type Validation
            received_mime = response.headers.get('Content-Type', '').lower()
            mime_warning = None
            match_found = True # Assume it matches unless we check and it doesn't
            
            if is_valid and expected_mime:
                accepted_types = [t.strip().lower() for t in expected_mime.split(',')]
                
                match_found = False
                for t in accepted_types:
                    if t in received_mime:
                        match_found = True
                        break
                
                if not match_found:
                    # --- Smart Recovery Logic ---
                    # If we expected JSON but got HTML, and this is not already a recovery attempt
                    if 'application/json' in expected_mime and 'text/html' in received_mime and not is_recovery_attempt:
                        self.logger.info(f"Attempting smart recovery for {url}: Expected JSON, got HTML.")
                        try:
                            # Debug: Log a snippet of the HTML
                            self.logger.info(f"HTML Snippet (first 500 chars): {response.text[:500]}")
                            
                            doc = html.fromstring(response.text)
                            
                            # Debug: Log ALL links found
                            all_links = doc.xpath('//a/@href')
                            self.logger.info(f"All links found on page: {all_links}")

                            # Look for links ending in .json
                            json_links = doc.xpath('//a[contains(@href, ".json")]/@href')
                            self.logger.info(f"Found potential JSON links: {json_links}")
                            
                            if json_links:
                                recovery_url = urljoin(response.url, json_links[0])
                                self.logger.info(f"Attempting to validate recovery URL: {recovery_url}")
                                recovery_result = self.validate_url(recovery_url, api_type, is_recovery_attempt=True)
                                if recovery_result.get('valid'):
                                    recovery_result['note'] = f"Recovered from HTML page; original URL was {url}"
                                    self.logger.info(f"Smart recovery SUCCESS for {url} via {recovery_url}")
                                    return recovery_result
                                else:
                                    self.logger.warning(f"Smart recovery FAILED for {url} via {recovery_url}: {recovery_result.get('error', 'Unknown error')}")
                            else:
                                self.logger.info(f"No JSON links found on HTML page for {url}.")
                                
                                # --- Fallback for Swagger UI / SPA ---
                                # This isnt perfect, but should catch a number of cases JavaScript rendered content,
                                # where we don't get the full html in the response
                                # like e.g.: "https://coscine.rwth-aachen.de/coscine/api/swagger/index.html"
                                # Alternative would be a headless browser, but that seems a but heavy
                                if 'swagger-ui' in response.text or 'id="swagger-ui"' in response.text:
                                    self.logger.info(f"Detected Swagger UI on {url}. Marking as valid (content unverified).")
                                    return {
                                        "valid": True,
                                        "status_code": response.status_code,
                                        "content_type": received_mime,
                                        "url": target_url,
                                        "expected_content_type": expected_mime,
                                        "note": "Received HTML (likely JavaScript-rendered Swagger UI) instead of JSON. Status 200 OK suggests service is active. Arguably not a machine readable endpoint."
                                    }

                        except Exception as e:
                            self.logger.error(f"Error during smart recovery for {url}: {e}")
                            pass # If parsing or recovery fails, just proceed to the normal error

                    # Strict validation: Mark as invalid
                    is_valid = False
                    mime_warning = f"Invalid Content-Type: expected '{expected_mime}', got '{received_mime}'"

            # Check for redirects
            redirect_chain = []
            if response.history:
                for resp in response.history:
                    redirect_chain.append({
                        "status_code": resp.status_code,
                        "url": resp.url
                    })

            result = {
                "valid": is_valid,
                "status_code": response.status_code,
                "content_type": received_mime,
                "url": target_url,
                "expected_content_type": expected_mime if expected_mime else None
            }
            
            if redirect_chain:
                result["redirects"] = redirect_chain
                result["final_url"] = response.url
            
            if mime_warning:
                result["error"] = mime_warning
                
            return result

        except requests.RequestException as e:
            return {"valid": False, "error": str(e), "url": target_url}

    def _check_generic_http(self, url):
        """
        Standard GET for types without specific path requirements.
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            
            # Check for redirects
            redirect_chain = []
            if response.history:
                for resp in response.history:
                    redirect_chain.append({
                        "status_code": resp.status_code,
                        "url": resp.url
                    })
            
            result = {
                "valid": 200 <= response.status_code < 400,
                "status_code": response.status_code,
                "content_type": response.headers.get('Content-Type', 'unknown').lower(),
                "url": url
            }
            
            if redirect_chain:
                result["redirects"] = redirect_chain
                result["final_url"] = response.url
                
            return result

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
