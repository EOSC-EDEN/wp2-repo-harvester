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

    def transform(self, raw_content: str, crosswalk_id: str) -> dict:
        """
        Uploads content to MSCR /transform endpoint.
        
        :param raw_content: The XML or JSON string to transform.
        :param crosswalk_id: The UUID of the crosswalk registered in MSCR.
        """
        if MOCK_MODE:
            return self._get_mock_response()

        if not self.token or "PASTE_YOUR_TOKEN" in self.token:
            logger.error("Missing MSCR_API_TOKEN. Please set it in config.py or environment.")
            return {}

        endpoint = f"{self.api_url}/transform"
        
        # MSCR Authentication Header
        headers = {
            'X-API-KEY': self.token
        }

        # The /transform endpoint typically expects a file upload (multipart/form-data)
        # Pass the parameters expected by the datamodel-api
        data = {
            'crosswalkId': crosswalk_id,
            'outputMethod': 'text'  # We expect JSON text back
        }
        
        # Simulate a file upload using the raw content string
        files = {
            'file': ('upload.txt', raw_content, 'text/plain')
        }

        try:
            logger.info(f"POST {endpoint} (Crosswalk: {crosswalk_id})")
            
            response = requests.post(
                endpoint,
                headers=headers,
                data=data,
                files=files,
                timeout=MSCR_TIMEOUT
            )
            
            if response.status_code != 200:
                logger.error(f"MSCR Error {response.status_code}: {response.text}")
                return {}

            # Parse the result
            # The API usually returns the transformed text directly.
            try:
                return response.json()
            except json.JSONDecodeError:
                # If it returns a string of JSON but content-type isn't application/json
                return json.loads(response.text)

        except Exception as e:
            logger.error(f"MSCR Request Failed: {e}")
            return {}

    def _get_mock_response(self):
        logger.warning("MSCR Mock Mode is ON.")
        return {
            "@context": "https://eden-fidelis.eu/context.jsonld",
            "@type": "dcat:Catalog",
            "title": "MOCK DATA (Real API not called)",
            "services": []
        }