import requests
import logging
import json
from .config import MSCR_API_URL, MSCR_API_TOKEN, MSCR_TIMEOUT, MOCK_MODE

logger = logging.getLogger(__name__)

class MSCRClient:
    """
    Client to communicate with the production MSCR API.
    """

    def __init__(self):
        self.api_url = MSCR_API_URL
        self.token = MSCR_API_TOKEN
        self.headers = {
            'X-API-KEY': self.token,
            'Accept': 'application/json'
        }

    def check_connection(self):
        """Simple ping to check if token works (e.g., getting user info)."""
        if not self.token:
            return False
        try:
            # /v2/user is a reliable endpoint to test auth
            endpoint = f"{self.api_url}/user"
            response = requests.get(endpoint, headers=self.headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False

    def get_all_crosswalks(self):
        """
        Retrieves a list of all available crosswalks using the frontend search API.
        """
        # CORRECTED: Use the search endpoint instead of the direct resource endpoint
        endpoint = f"{self.api_url}/frontend/mscrSearch"
        
        # Filter by type 'CROSSWALK' to avoid getting Schemas
        params = {
            'type': 'CROSSWALK',
            'limit': 100  # Request enough items to find what we need
        }

        try:
            response = requests.get(endpoint, headers=self.headers, params=params, timeout=MSCR_TIMEOUT)
            
            if response.status_code == 200:
                data = response.json()
                
                # The search API often wraps results. 
                # We handle a direct list or a wrapper like {'items': [...]} or {'content': [...]}
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get('items') or data.get('content') or data.get('results') or []
                
                logger.warning(f"Unexpected response format: {type(data)}")
                return []
            else:
                logger.error(f"Failed to list crosswalks: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching crosswalks: {e}")
            return []

    def transform(self, raw_content: str, crosswalk_id: str, source_format="xml"):
        """
        Uploads content to MSCR /transform endpoint.
        """
        if MOCK_MODE:
            return self._get_mock_response()

        if not self.token:
            logger.error("Missing MSCR_API_TOKEN.")
            return {}

        endpoint = f"{self.api_url}/transform"
        
        # 1. Prepare Parameters
        data = {
            'crosswalkId': crosswalk_id,
            'outputMethod': 'json' 
        }
        
        # 2. Prepare File (Multipart Upload)
        # MSCR needs a file-like object. 
        # We explicitly set the filename and mime-type.
        filename = "upload.json" if source_format == "json" else "upload.xml"
        mime_type = "application/json" if source_format == "json" else "text/xml"

        files = {
            'file': (filename, raw_content, mime_type)
        }

        try:
            logger.info(f"Sending content to MSCR (Crosswalk: {crosswalk_id})...")
            
            # Note: headers should NOT include Content-Type, requests sets it for multipart
            response = requests.post(
                endpoint,
                headers={'X-API-KEY': self.token}, 
                data=data,
                files=files,
                timeout=MSCR_TIMEOUT
            )
            
            if response.status_code == 200:
                # Success - return the JSON
                try:
                    return response.json()
                except json.JSONDecodeError:
                    return json.loads(response.text)
            else:
                logger.error(f"MSCR Transformation Error {response.status_code}: {response.text}")
                return None

        except Exception as e:
            logger.error(f"MSCR Request Failed: {e}")
            return None

    def _get_mock_response(self):
        return {
            "@context": "https://eden-fidelis.eu/context.jsonld",
            "@type": "dcat:Catalog",
            "title": "MOCK DATA",
            "services": []
        }