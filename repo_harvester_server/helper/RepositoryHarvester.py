import json
from datetime import datetime
import requests
from urllib.parse import urlparse
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.config import FUSEKI_PATH

from .Re3DataHarvester import Re3DataHarvester
from .FAIRsharingHarvester import FAIRsharingHarvester

class RepositoryHarvester:
    """
    The main orchestrator for the harvesting process.
    It coordinates the self-hosted harvesting and the registry harvesting.
    """
    extractors = {
        'embedded_jsonld': 'Embedded JSON-LD Metadata Extraction',
        'meta_tags': 'Embedded Meta-Tags Metadata Extraction',
        'linked_jsonld': 'Linked (signposting) JSON-LD Metadata Extraction',
        'fairicat_services': 'FAIRiCAT / Linkset / API Catalog Discovery',
        'feed_services': 'Feed (Atom/RSS) Service Discovery',
        'sitemap_service': 'Sitemap Service Discovery',
        'open_search': 'OpenSearch Service Discovery',
        're3data': 're3data.org Registry Harvesting',
        'fairsharing': 'FAIRsharing.org Registry Harvesting'
    }

    def __init__(self, catalog_url):
        self.catalog_url = catalog_url
        self.catalog_html = None
        self.metadata = []
        self.metadata_helper = None

        if not str(self.catalog_url).startswith('http'):
            print('Invalid repo URI:', self.catalog_url)
            return

        headers = {
            'User-Agent': 'EDEN-Harvester/1.0 (Research Project; mailto:admin@eden-fidelis.eu)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        try:
            response = requests.get(self.catalog_url, headers=headers, timeout=10)
            response.raise_for_status()
            self.catalog_html = response.text
            self.metadata_helper = MetadataHelper(self.catalog_url, response.text, response.headers)
        except requests.exceptions.RequestException as e:
            print(f"Failed to fetch {self.catalog_url}: {e}")

    def merge_metadata(self, new_metadata, source):
        """
        Adds a new metadata chunk to the main list, tagging it with its source.
        """
        def clean_none(obj):
            if isinstance(obj, dict):
                return {k: clean_none(v) for k, v in obj.items() if v is not None}
            elif isinstance(obj, list):
                return [clean_none(item) for item in obj]
            else:
                return obj
        if new_metadata:
            new_metadata = clean_none(new_metadata)
            self.metadata.append({'source': source, 'metadata': new_metadata})

    def harvest(self):
        """
        Main entry point for the harvesting process.
        """
        self.harvest_self_hosted_metadata()
        self.harvest_registry_metadata()
        return self.export()

    def harvest_registry_metadata(self):
        """
        Orchestrates harvesting from all configured external registries.
        """
        print("--- Starting Registry Harvesting ---")
        
        re3data_harvester = Re3DataHarvester()
        re3data_meta = re3data_harvester.harvest(self.catalog_url)
        print(f"RAW re3data METADATA: {json.dumps(re3data_meta, indent=4)}")
        self.merge_metadata(re3data_meta, 're3data')

        fairsharing_harvester = FAIRsharingHarvester()
        fairsharing_meta = fairsharing_harvester.harvest(self.catalog_url)
        print(f"RAW FAIRsharing METADATA: {json.dumps(fairsharing_meta, indent=4)}")
        self.merge_metadata(fairsharing_meta, 'fairsharing')

        print("--- Finished Registry Harvesting ---")

    def harvest_self_hosted_metadata(self):
        """
        Harvests metadata directly from the repository landing page.
        """
        if not self.catalog_html or not self.metadata_helper:
            print('Cannot perform self-hosted harvest; initial fetch failed.')
            return
        
        print("--- Starting Self-Hosted Harvesting ---")
        mode = 'rdflib'
        try:
            self.merge_metadata(self.metadata_helper.get_embedded_jsonld_metadata(mode), 'embedded_jsonld')
            self.merge_metadata(self.metadata_helper.get_html_meta_tags_metadata(), 'meta_tags')
            for link in self.metadata_helper.signposting_helper.get_links('describedby', 'application/ld+json'):
                self.merge_metadata(self.metadata_helper.get_linked_jsonld_metadata(link.get('link'), mode), 'linked_jsonld')
            self.merge_metadata(self.metadata_helper.get_fairicat_metadata(), 'fairicat_services')
            self.merge_metadata(self.metadata_helper.get_feed_metadata(), 'feed_services')
            self.merge_metadata(self.metadata_helper.get_sitemap_service_metadata(), 'sitemap_service')
            print("--- Finished Self-Hosted Harvesting ---")
        except Exception as e:
            print(f"An error occurred during self-hosted harvest: {e}")

    def export(self, save=False):
        """
        Transforms and exports each harvested metadata chunk to DCAT JSON-LD.
        """
        print("--- Starting Export ---")
        final_records = []
        if not self.metadata:
            print("No metadata was harvested, nothing to export.")
            return final_records

        for m in self.metadata:
            metadata_chunk = m.get('metadata')
            source = m.get('source')
            if not metadata_chunk:
                continue

            export_record = self.metadata_helper.export(metadata_chunk)
            
            primary_source = export_record.get('prov:hadPrimarySource')
            if primary_source and (primary_source.get('dct:title') or primary_source.get('dct:description')):
                now = datetime.now()
                date_time = now.strftime("%Y-%m-%dT%H:%M:%S")
                graph_id = f'eden://harvester/{source}/{self.catalog_url}'

                export_record['@id'] = graph_id
                export_record['dct:issued'] = date_time
                
                if 'prov:wasGeneratedBy' in export_record:
                    export_record['prov:wasGeneratedBy']['prov:startedAtTime'] = date_time
                    export_record['prov:wasGeneratedBy']['prov:name'] = self.extractors.get(source, "Unknown Harvester")
                    export_record['prov:wasGeneratedBy']['@id'] = f'eden://harvester/{source}'

                if 'prov:hadPrimarySource' in export_record:
                     export_record['prov:hadPrimarySource']['@id'] = self.catalog_url

                final_records.append(export_record)
                print(f"Successfully processed record from source: {source}")

                if save:
                    self.save(graph_id, json.dumps(export_record))
            else:
                print(f"Skipping export for source '{source}': No meaningful data to map.")
        
        print("--- Finished Export ---")
        return final_records

    def save(self, graph_uri, graph_jsonld):
        """
        Saves a named graph in a JENA FUSEKI triple store.
        """
        headers = {"Content-Type": "application/ld+json"}
        try:
            response = requests.put(
                FUSEKI_PATH,
                params={"graph": graph_uri},
                data=graph_jsonld,
                headers=headers
            )
            response.raise_for_status()
            print(f"Successfully saved graph {graph_uri} to Fuseki. Status: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Failed to save graph {graph_uri} to Fuseki: {e}")
