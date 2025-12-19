import json
from datetime import datetime
import requests
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

from urllib.parse import urlparse
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester

from repo_harvester_server.config import FUSEKI_PATH

class RepositoryHarvester:
    logger = logging.getLogger('RepositoryHarvester')
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
        self.catalog_ids = [self.catalog_url]

        if not str(self.catalog_url).startswith('http'):
            self.logger.error("Invalid repo URI: %s", self.catalog_url)

        # Use a polite User-Agent for research harvesting
        headers = {
            'User-Agent': 'EDEN-Harvester/1.0 (Research Project; mailto:admin@eden-fidelis.eu)',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        try:
            response = requests.get(self.catalog_url, headers=headers, timeout=10)
            response.raise_for_status()
            #using the canonical url to identify the resource
            if response.url != self.catalog_url:
                self.logger.warning("Redirected to URI: %s , so will use this as the canonical URL", response.url)
                self.catalog_ids.append(response.url)
                self.catalog_url = response.url
            self.catalog_html = response.text
            self.catalog_header = response.headers
            self.metadata_helper = MetadataHelper(self.catalog_url, self.catalog_html, self.catalog_header)
            self.logger.info('Catalog URL harvested: '+ self.catalog_url)
        except requests.exceptions.RequestException as e:
            self.logger.error("Failed to fetch URI: %s", self.catalog_url)

    def merge_metadata(self, new_metadata, source = None):
        """
        Merges (rather adds) new metadata into a list of metadata objects.
        Merging should later be done using the individual metadata /service graphs
        """

        def clean_none(obj):
            """
            Recursively remove keys with value None from dictionaries and lists.
            """
            if isinstance(obj, dict):
                return {
                    k: clean_none(v)
                    for k, v in obj.items()
                    if v is not None
                }
            elif isinstance(obj, list):
                return [clean_none(item) for item in obj]
            else:
                return obj
        if new_metadata:
            new_metadata = clean_none(new_metadata)
            if not new_metadata.get('identifier'):
                if self.catalog_url:
                    new_metadata['identifier'] = self.catalog_url
            self.metadata.append({'source': source, 'metadata': new_metadata})

    def harvest(self, where=None):
        """
        Main entry point.
        1. Tries to harvest directly from the website (Self-Hosted).
        2. If that fails to find a Title, falls back to re3data (Registry).
        :param where str: default None, the source to be harvested can be either 'self-hosted' or 'registry'
        """
        if not where or where == 'self-hosted':
            self.harvest_self_hosted_metadata()
        if not where or where == 'registry':
            self.harvest_registry_metadata()
        return self.export(True)

    def harvest_registry_metadata(self):
        """
        Orchestrates harvesting from all configured external registries.
        """
        self.logger.info("--- Starting Registry Harvesting ---")

        re3data_harvester = Re3DataHarvester()
        re3data_meta = re3data_harvester.harvest(self.catalog_url)
        print(f"RAW re3data METADATA: {json.dumps(re3data_meta, indent=4)}")
        self.merge_metadata(re3data_meta, 're3data')

        fairsharing_harvester = FAIRsharingHarvester()
        fairsharing_meta = fairsharing_harvester.harvest(self.catalog_url)
        print(f"RAW FAIRsharing METADATA: {json.dumps(fairsharing_meta, indent=4)}")
        self.merge_metadata(fairsharing_meta, 'fairsharing')

        self.logger.info("--- Finished Registry Harvesting ---")

    def harvest_self_hosted_metadata(self):
        """
        Harvests metadata directly from the repository landing page.
        """
        if not self.catalog_html or not self.metadata_helper:
            self.logger.warning('Cannot perform self-hosted harvest; initial fetch failed.')
            return
        
        self.logger.info("--- Starting Self-Hosted Harvesting ---")
        mode = 'simple'
        try:
            self.merge_metadata(self.metadata_helper.get_embedded_jsonld_metadata(mode), 'embedded_jsonld')
            self.merge_metadata(self.metadata_helper.get_html_meta_tags_metadata(), 'meta_tags')
            for link in self.metadata_helper.signposting_helper.get_links('describedby', 'application/ld+json'):
                self.merge_metadata(self.metadata_helper.get_linked_jsonld_metadata(link.get('link'), mode), 'linked_jsonld')
            self.merge_metadata(self.metadata_helper.get_fairicat_metadata(), 'fairicat_services')
            self.merge_metadata(self.metadata_helper.get_feed_metadata(), 'feed_services')
            self.merge_metadata(self.metadata_helper.get_sitemap_service_metadata(), 'sitemap_service')
            self.logger.info("--- Finished Self-Hosted Harvesting ---")
        except Exception as e:
            self.logger.error(f"An error occurred during self-hosted harvest: {e}")

    def export(self, save=False):
        """
        Exports harvested metadata to DCAT JSON-LD.
        It uses the MetadataHelper export method which is based on JMESPATH see: JMESPATHQueries.py
        Some additional metadata is added here to the resulting

        :param save bool , indicates if the record shall be saved or not (in FUSEKI).
        """
        self.logger.info("--- Starting Export ---")
        final_records = []
        if not self.metadata:
            print("No metadata was harvested, nothing to export.")
            return final_records

        for m in self.metadata:
            metadata_chunk = m.get('metadata')
            source = m.get('source')
            if not metadata_chunk:
                continue

            if  metadata_chunk.get('services'):
                if isinstance(metadata_chunk['services'], dict):
                    metadata_chunk['services'] =  list(metadata_chunk['services'].values())

            export_record = self.metadata_helper.export(metadata_chunk)
            primary_source = export_record.get('prov:hadPrimarySource')
            #this would ignore feed metadata etc which have no repo info per se
            if primary_source:
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
                self.logger.info(f"Successfully processed record from source: {source}")
                if save:
                    self.save(graph_id, json.dumps(export_record))
            else:
                 self.logger.info(f"Skipping export for source '{source}': No meaningful data to map.")
                #print(f"Skipping export for source '{source}': No meaningful data to map.")

        self.logger.info("--- Finished Export ---")
        return final_records

    def save(self, graph_uri, graph_jsonld):
        """
        Saves a named graph in a JENA FUSEKI triple store
        :param graph_uri:
        :param graph_jsonld:
        :return:
        """
        #TODO: HTTP Basic Auth
        #TODO: check if server is running etc..
        try:
            headers = {
                "Content-Type": "application/ld+json"
            }

            # Use graph store protocol
            response = requests.put(
                FUSEKI_PATH,
                params={"graph": graph_uri},
                data=graph_jsonld,
                headers=headers
            )
            print("Status:", response.status_code)
            print(response.text)
        except Exception as e:
            self.logger.error(f"An error occurred while saving graph: {e}")
