import requests
import logging
import json
from .client import MSCRClient
from .config import CROSSWALK_IDS, MOCK_MODE

logger = logging.getLogger(__name__)

class MSCRHarvester:
    """
    Orchestrates the harvesting and transformation process.
    """

    def __init__(self, repo_url: str):
        self.repo_url = repo_url
        self.metadata = {}
        self.client = MSCRClient()
        self._raw_content = None
        self._content_type = None

    def harvest(self):
        logger.info(f"🌾 MSCR Harvester starting for: {self.repo_url}")
        
        # 1. Fetch Data
        if not self._fetch_remote_content():
            logger.error("❌ Failed to fetch content from repository.")
            return

        # 2. Determine Crosswalk UUID
        crosswalk_uuid, source_fmt = self._determine_crosswalk_and_format()
        
        # In Mock Mode, we proceed even without a valid UUID
        if not MOCK_MODE and (not crosswalk_uuid or "0000" in crosswalk_uuid):
            logger.error("❌ No valid Crosswalk ID configured. Please create one in MSCR.")
            return

        # 3. Transform via MSCR
        mode_str = "MOCK" if MOCK_MODE else "REAL"
        logger.info(f"🔄 Delegating transformation ({mode_str} MODE)...")
        
        result = self.client.transform(
            raw_content=self._raw_content,
            crosswalk_id=crosswalk_uuid,
            source_format=source_fmt
        )

        if result:
            self.metadata = result
            logger.info("✅ Transformation successful.")
            # For debugging, we can print a snippet of the result
            logger.debug(f"Result snippet: {str(result)[:100]}...")
        else:
            logger.error("❌ Transformation failed or returned empty.")

    def _fetch_remote_content(self):
        headers = {
            'User-Agent': 'EDEN-Harvester/1.0',
            'Accept': 'application/json, application/xml, text/html'
        }
        try:
            # We verify SSL=False only if you have issues with specific repo certificates, 
            # otherwise keep verify=True for security.
            resp = requests.get(self.repo_url, headers=headers, timeout=15)
            
            if resp.status_code == 200:
                self._raw_content = resp.text
                self._content_type = resp.headers.get('Content-Type', '').lower()
                logger.info(f"Fetched {len(self._raw_content)} bytes (Type: {self._content_type})")
                return True
            else:
                logger.warning(f"HTTP GET failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Network error: {e}")
        return False

    def _determine_crosswalk_and_format(self):
        """
        Decides which Crosswalk UUID to use based on the content or URL.
        Returns: (UUID, format_string)
        """
        # Logic: Is it re3data?
        # Check URL or Content content
        if "re3data.org" in self.repo_url or "re3data" in (self._raw_content or "")[:500]:
            return CROSSWALK_IDS.get('re3data_to_eden'), "xml"

        # Logic: Is it JSON-LD?
        if "application/ld+json" in (self._content_type or "") or "application/json" in (self._content_type or ""):
            return CROSSWALK_IDS.get('schemaorg_to_eden'), "json"

        # Default fallback
        return CROSSWALK_IDS.get('re3data_to_eden'), "xml"