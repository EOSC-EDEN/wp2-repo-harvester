import json
from datetime import datetime

import requests
from lxml import etree
from urllib.parse import urlparse
from repo_harvester_server.helper.MetadataHelper import MetadataHelper

class CatalogMetadataHarvester:

    # an internal vocab to indicate the sources of metadata
    extractors = {
        'embedded_jsonld': 'Embedded JSON-LD Metadata Extraction',
        'meta_tags': 'Embedded Meta-Tags Metadata Extraction',
        'linked_jsonld': 'Linked (signposting) JSON-LD Metadata Extraction',
        'fairicat_services': 'FAIRiCAT / Linkset / API Catalog Discovery',
        'feed_services': 'Feed (Atom/RSS) Service Discovery',
        'sitemap_service': 'Sitemap Service Discovery',
        'open_search': 'OpenSearch Service Discovery'
    }

    def __init__(self, catalog_url):
        self.catalog_url = catalog_url
        self.catalog_html = None
        self.metadata = []
        if not str(self.catalog_url).startswith('http'):
            print('Invalid repo URI:', self.catalog_url)
            return

            # Use a polite User-Agent for research harvesting
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
            self.metadata_helper = MetadataHelper(self.catalog_url, self.catalog_html, self.catalog_header)
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch {self.catalog_url}: {e}")


    def merge_metadata(self, new_metadata, source = None):
        """
        Merges (rather adds) new metadata into a list of metadata objects.
        Merging should later be done using the individual metadata /service graphs
        """
        if new_metadata:
            self.metadata.append({'source': source, 'metadata': new_metadata})
        '''if new_metadata:
            for key, value in new_metadata.items():
                # For lists (services), append them
                if key == 'services' and isinstance(value, list):
                    if 'services' not in self.metadata:
                        self.metadata['services'] = []
                    self.metadata['services'].extend(value)
                # For scalars (title, id), set if missing or overwrite
                else:
                    self.metadata[key] = value'''

    def harvest(self):
        """
        Main entry point.
        1. Tries to harvest directly from the website (Self-Hosted).
        2. If that fails to find a Title, falls back to re3data (Registry).
        """
        self.harvest_self_hosted_metadata()
        
        # Fallback: If no title found via self-hosted, try Registry
        #if not self.metadata.get('title'):
        #    print(f"Self-hosted harvest incomplete for {self.catalog_url}. Attempting Registry harvest...")
        # TODO: uncomment later ;)
        #    self.harvest_registry_metadata()
        self.export()

    def harvest_registry_metadata(self):
        """
        Harvests metadata from the re3data.org API.
        """
        try:
            # Strategy 1: Search by full URL
            if self._search_re3data(self.catalog_url):
                return

            # Strategy 2: Search by Domain only.
            # This helps if re3data indexed 'http' but we have 'https', 
            # or if the path varies slightly (e.g. ssh.datastations.nl).
            domain = urlparse(self.catalog_url).netloc
            if domain:
                print(f"Retrying re3data search with domain: {domain}")
                self._search_re3data(domain)
                        
        except Exception as e:
            print(f"Registry Harvest Error: {e}")

    def _search_re3data(self, query):
        """
        Helper to search re3data API and fetch details for the first match.
        Returns True if a match was found and parsed.
        """
        api_url = f"https://www.re3data.org/api/beta/repositories?query={query}"
        resp = requests.get(api_url, timeout=10)
        
        if resp.status_code != 200:
            return False
        
        try:
            root = etree.fromstring(resp.content)
            # Namespace is required for re3data XML
            ns = {"r3d": "http://www.re3data.org/schema/2-2"}
            
            # Find the first repository link
            repo_link = root.find(".//r3d:link", ns)
            if repo_link is not None:
                href = repo_link.get("href")
                print(f"Found re3data entry: {href}")
                self._fetch_re3data_details(href)
                return True
        except Exception as e:
            print(f"Error parsing re3data search result: {e}")
            
        return False

    def _fetch_re3data_details(self, url):
        """
        Fetches the detailed XML for a specific repository from re3data
        and maps it to our EDEN Schema.
        """
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            try:
                root = etree.fromstring(resp.content)
                ns = {"r3d": "http://www.re3data.org/schema/2-2"}
                
                # Extract Title
                name = root.find(".//r3d:repositoryName", ns)
                if name is not None:
                    self.metadata['title'] = name.text
                
                # Extract Description
                desc = root.find(".//r3d:description", ns)
                if desc is not None:
                    self.metadata['description'] = desc.text
                
                # Extract re3data ID
                r3d_id = root.find(".//r3d:re3data.orgIdentifier", ns)
                if r3d_id is not None:
                    self.metadata['re3dataID'] = r3d_id.text
                
                # Extract Publisher (Institution)
                inst = root.find(".//r3d:institutionName", ns)
                if inst is not None:
                    self.metadata['publisher'] = {
                        "type": "org:Organization",
                        "name": inst.text
                    }

                # Extract Landing Page and set ID
                url_node = root.find(".//r3d:repositoryURL", ns)
                if url_node is not None:
                    self.metadata['landingPage'] = url_node.text
                    # Use Landing Page as ID if we don't have one
                    if not self.metadata.get('id'):
                        self.metadata['id'] = url_node.text

            except Exception as e:
                print(f"Error parsing re3data details: {e}")

    def harvest_self_hosted_metadata(self):
        """
        Harvests metadata directly from the repository landing page
        using Signposting, JSON-LD (Embedded/Linked), and HTML Meta tags.
        """
        mode = 'rdflib' #otherwise the GraphHelper will be used
        if self.catalog_html:
            try:

                # 1. Signposting Extraction (Link headers, <link> tags)

                # 2. Metadata Extraction
                # A1. Embedded JSON-LD
                self.merge_metadata(self.metadata_helper.get_embedded_jsonld_metadata(mode), 'embedded_jsonld')
                # A2. Embedded meta tags
                self.merge_metadata(self.metadata_helper.get_html_meta_tags_metadata(), 'meta_tags')

                print('EMBEDDED METADATA extracted.')

                # B. Linked JSON-LD (via 'describedby' links)
                for link in self.metadata_helper.signposting_helper.get_links('describedby', 'application/ld+json'):
                    self.merge_metadata(self.metadata_helper.get_linked_jsonld_metadata(link.get('link'), mode), 'linked_jsonld')

                # C. FAIRiCAT / Linksets
                self.merge_metadata(self.metadata_helper.get_fairicat_metadata(), 'fairicat_services')

                # D. FEED Services
                self.merge_metadata(self.metadata_helper.get_feed_metadata(), 'feed_services')

                # E. Sitemap Service
                self.merge_metadata(self.metadata_helper.get_sitemap_service_metadata(), 'sitemap_service')

                print('MERGED METADATA: ', json.dumps(self.metadata, indent=4))

            except Exception as e:
                print(f"Self-Hosted Harvest Error: {e}")
        else:
            print('NO METADATA found at :', self.catalog_url)

    def export(self):
        """
        Exports harvested metadata to DCAT JSON-LD.
        It uses the MetadataHelper export method which is based on JMESPATH see: JMESPATHQueries.py
        Some additional metadata is added here to the resulting dict
        """
        export_metadata = {}
        if self.metadata:
            for m in self.metadata:
                metadata = m.get('metadata', {})
                source = m.get('source')
                if  metadata.get('services'):
                    metadata['services'] =  list(metadata['services'].values())
                export_metadata = self.metadata_helper.export(metadata)


                if export_metadata.get('prov:hadPrimarySource'):
                    export_metadata['prov:hadPrimarySource']['@id'] =  str(self.catalog_url)
                now = datetime.now()
                date_time = now.strftime("%Y-%m-%dT%H:%M:%S")
                if export_metadata.get('prov:wasGeneratedBy'):
                    export_metadata['prov:wasGeneratedBy']['prov:startedAtTime'] = date_time
                    export_metadata['prov:wasGeneratedBy']['prov:name'] = self.extractors.get(source)
                    export_metadata['prov:wasGeneratedBy']['@id'] = 'eden://harvester/'+source
                export_metadata['dct:issued'] = date_time
                export_metadata['@id'] = 'eden://harvester/'+str(source)+'/'+str(self.catalog_url)
                print('DCAT: ', json.dumps(export_metadata, indent=4))
        return export_metadata