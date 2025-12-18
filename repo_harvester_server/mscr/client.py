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
            # /v2/user is a good endpoint to test auth
            endpoint = f"{self.api_url}/user"
            response = requests.get(endpoint, headers=self.headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False

    def get_all_crosswalks(self):
        """
        Retrieves a list of all available crosswalks to help identify correct UUIDs.
        """
        endpoint = f"{self.api_url}/crosswalk"
        try:
            response = requests.get(endpoint, headers=self.headers, timeout=MSCR_TIMEOUT)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to list crosswalks: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching crosswalks: {e}")
            return []

    def transform(self, raw_content: str, crosswalk_id: str, source_format="xml"):
        """
        Uploads content to MSCR /transform endpoint.
        
        :param raw_content: The XML or JSON string to transform.
        :param crosswalk_id: The UUID of the crosswalk.
        :param source_format: 'xml' or 'json' (used to name the dummy file).
        """
        if MOCK_MODE:
            return self._get_mock_response()

        if not self.token:
            logger.error("Missing MSCR_API_TOKEN.")
            return {}

        endpoint = f"{self.api_url}/transform"
        
        # Prepare params
        params = {
            'crosswalkId': crosswalk_id,
            'outputMethod': 'json' # We want the result back as JSON
        }
        
        # Prepare file payload
        # MSCR determines input type often by file extension or content sniffing
        filename = "upload.json" if source_format == "json" else "upload.xml"
        mime_type = "application/json" if source_format == "json" else "text/xml"

        files = {
            'file': (filename, raw_content, mime_type)
        }

        try:
            logger.info(f"Sending content to MSCR (Crosswalk: {crosswalk_id})...")
            
            # Note: Do not include Content-Type header manually when using 'files', 
            # requests handles multipart boundary automatically.
            response = requests.post(
                endpoint,
                headers={'X-API-KEY': self.token}, # Only auth header here
                data=params,
                files=files,
                timeout=MSCR_TIMEOUT
            )
            
            if response.status_code == 200:
                # The API returns the transformed JSON content directly
                try:
                    return response.json()
                except json.JSONDecodeError:
                    # Fallback if it returns stringified JSON
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