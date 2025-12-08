import json
import re
from urllib.parse import urlparse, urljoin
import requests
from lxml import html

from repo_harvester_server.helper.SignPostingHelper import SignPostingHelper
from repo_harvester_server.helper.MetadataHelper import MetadataHelper


class CatalogMetadataHarvester:
    def __init__(self, catalog_url):
        self.catalog_url = catalog_url
        self.catalog_html = None
        self.signposting_links = []
        self.metadata = {}

    def merge_metadata(self, new_metadata):
        if new_metadata:
            for key, value in new_metadata.items():
                if key not in self.metadata:
                    self.metadata[key] = new_metadata[key]
                # If both are dicts (e.g. services), ideally we merge them, 
                # but for MVP overwriting/appending keys is okay for now.

    def harvest(self):
        self.harvest_self_hosted_metadata()
        self.harvest_registry_metadata()

    def harvest_registry_metadata(self, registry='re3data'):
        # Placeholder for re3data harvest logic
        pass

    def harvest_self_hosted_metadata(self):
        # Validate URL
        if not str(self.catalog_url).startswith('http'):
            print('Invalid repo URI:', self.catalog_url)
            return

        # Prepare Request: User-Agent prevents blocking by Zenodo/Cloudflare
        headers = {
            'User-Agent': 'EDEN-Harvester/1.0 (Research Project; mailto:admin@eden-fidelis.eu)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        try:
            response = requests.get(self.catalog_url, headers=headers, timeout=10)
            
            if response.status_code != 200:
                print(f"Failed to fetch {self.catalog_url}: Status {response.status_code}")
                return

            self.catalog_html = response.text
            self.catalog_header = response.headers

            # 1. Signposting
            signposting_helper = SignPostingHelper(self.catalog_url, self.catalog_html, self.catalog_header)
            self.signposting_links = signposting_helper.links
            
            # 2. Metadata Extraction
            metadata_helper = MetadataHelper()

            # A. Embedded JSON-LD
            embedded_jsonld = metadata_helper.get_embedded_jsonld_metadata(self.catalog_html)
            self.merge_metadata(embedded_jsonld)
            
            # B. Linked JSON-LD
            for jsonld_link in signposting_helper.get_links('describedby', 'application/ld+json'):
                linked_jsonld = metadata_helper.get_linked_jsonld_metadata(jsonld_link.get('link'))
                self.merge_metadata(linked_jsonld)
            
            # C. FAIRiCAT (Signposting Linksets)
            fairicat_metadata = signposting_helper.get_fairicat_metadata()
            self.merge_metadata(fairicat_metadata)

            print('MERGED METADATA: ', json.dumps(self.metadata, indent=4))

        except Exception as e:
            print(f"Harvest Error for {self.catalog_url}: {e}")