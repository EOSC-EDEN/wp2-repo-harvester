import requests
import logging
from .client import MSCRClient
from .config import CROSSWALK_IDS

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
        print(f"🌾 MSCR Harvester starting for: {self.repo_url}")
        
        # 1. Fetch Data
        if not self._fetch_remote_content():
            print("❌ Failed to fetch content from repository.")
            return

        # 2. Determine Crosswalk UUID
        crosswalk_uuid = self._determine_crosswalk()
        if not crosswalk_uuid:
            print("❌ No matching Crosswalk ID found in config.py for this source.")
            return

        # 3. Transform via MSCR
        print(f"🔄 Delegating transformation to MSCR (UUID: {crosswalk_uuid})...")
        result = self.client.transform(
            raw_content=self._raw_content,
            crosswalk_id=crosswalk_uuid
        )

        if result:
            self.metadata = result
            print("✅ Transformation successful.")
        else:
            print("❌ Transformation failed or returned empty.")

    def _fetch_remote_content(self):
        headers = {
            'User-Agent': 'EDEN-Harvester/1.0',
            'Accept': 'application/json, application/xml, text/html'
        }
        try:
            resp = requests.get(self.repo_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                self._raw_content = resp.text
                self._content_type = resp.headers.get('Content-Type', '')
                return True
        except Exception as e:
            logger.error(f"Network error: {e}")
        return False

    def _determine_crosswalk(self):
        """
        Decides which Crosswalk UUID to use based on the content or URL.
        """
        # Logic: Is it re3data?
        if "re3data.org" in self.repo_url or "re3data" in self._raw_content[:200]:
            return CROSSWALK_IDS.get('re3data_to_eden')

        # Logic: Is it JSON-LD?
        if "application/ld+json" in self._content_type:
            return CROSSWALK_IDS.get('schemaorg_to_eden')

        # Fallback / Default
        return CROSSWALK_IDS.get('schemaorg_to_eden')