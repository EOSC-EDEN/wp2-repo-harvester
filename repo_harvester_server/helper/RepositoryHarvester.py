import json
import os
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import logging

from rdflib import Graph

from repo_harvester_server.helper.RepositoryHarmonizer import RepositoryHarmonizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper

from repo_harvester_server.config import FUSEKI_PATH
from repo_harvester_server.helper.SPARQLQueries import GET_ALL_GRAPHS

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

        self.check_environment_variables()

        self.fuseki = FUSEKIHelper()

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
                self.logger.info("Redirected to URI: %s , so will use this as the canonical URL", response.url)
                self.catalog_ids.append(response.url)
                self.catalog_url = response.url
            self.catalog_html = response.text
            self.catalog_header = response.headers
            self.metadata_helper = MetadataHelper(self.catalog_url, self.catalog_html, self.catalog_header)
            self.logger.info('Catalog URL harvested: '+ self.catalog_url)
        except requests.exceptions.RequestException as e:
            self.logger.error("Failed to fetch URI: %s", self.catalog_url)

    def check_environment_variables(self):
        # to sucessfully perform the harvesting we need the FAIRsharing credentials as ENV variables
        # to be able to store the harvested metadata in FUSEKI we need FUSEKI credentials as ENV variables
        all_variables_available = True
        if not os.environ.get('FAIRSHARING_USERNAME'):
            self.logger.error("FAIRSHARING_USERNAME (OS env variable) not set – please define it before running")
            all_variables_available = False
        if not os.environ.get('FAIRSHARING_PASSWORD'):
            self.logger.error("FAIRSHARING_PASSWORD (OS env variable) not set – please define it before running")
            all_variables_available = False
        if not os.environ.get('FUSEKI_USERNAME'):
            self.logger.error("FUSEKI_USERNAME not set (OS env variable) not set – please define it before running")
            all_variables_available = False
        if not os.environ.get('FUSEKI_PASSWORD'):
            self.logger.error("FUSEKI_PASSWORD not set (OS env variable) not set – please define it before running")
            all_variables_available = False

        return all_variables_available


    def merge_metadata(self, new_metadata, source = None):
        """
        Merges (rather adds) new metadata into a list of metadata objects.
        Merging should later be done using the individual metadata /service graphs
        """

        def clean_none(obj):
            """
            Recursively remove keys with value None from dictionaries and lists.
            """
            try:
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
            except Exception as e:
                self.logger.error("Failed to clean metadata (remove empty values) : %s", e)
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
        2. Then harvest information from registries: FAIRsharing & re3data (Registry).
        :param where str: default None, the source to be harvested can be either 'self-hosted' or 'registry'
        """
        harvested_records = None
        if not where or where == 'self-hosted':
            self.harvest_self_hosted_metadata()
        if not where or where == 'registry':
            self.harvest_registry_metadata()
        # 3. final step: harmonize all records and save resulting graph in FUSEKI
        harvested_records = self.export_and_save(True)
        self.harmonize()
        return harvested_records

    def harvest_registry_metadata(self):
        """
        Orchestrates harvesting from external registries with cross-referencing.
        """
        self.logger.info("--- Starting Registry Harvesting ---")
        
        re3data_harvester = Re3DataHarvester()
        fairsharing_harvester = FAIRsharingHarvester()

        re3data_meta = None
        fairsharing_meta = None
        
        # 1. First pass on re3data
        re3data_meta = re3data_harvester.harvest(self.catalog_url)
        
        # 2. Harvest FAIRsharing, using re3data's findings if available
        fairsharing_id = None
        if re3data_meta:
            for identifier in re3data_meta.get('identifier', []):
                # Case-insensitive check for FAIRsharing ID
                if 'fairsharing' in identifier.lower():
                    fairsharing_id = identifier
                    break
        
        if fairsharing_id:
            fairsharing_meta = fairsharing_harvester.harvest_by_id(fairsharing_id)
        else:
            fairsharing_meta = fairsharing_harvester.harvest(self.catalog_url)

        # 3. Second pass on re3data (bridge), if the first pass failed
        if not re3data_meta and fairsharing_meta:
            # Try to find re3data ID in FAIRsharing metadata
            re3data_id = None
            for identifier in fairsharing_meta.get('identifier', []):
                # Simple check for re3data ID format
                if isinstance(identifier, str) and identifier.startswith('r3d'):
                    re3data_id = identifier
                    break
            if re3data_id:
                re3data_meta = re3data_harvester.harvest_by_id(re3data_id)
            # Fallback: Try bridging by name if no ID found
            elif fairsharing_meta.get('title'):
                self.logger.info(f"Bridging to re3data by name: {fairsharing_meta.get('title')}")
                re3data_meta = re3data_harvester.harvest_by_name(fairsharing_meta.get('title'))

        # 4. Merge all collected metadata
        self.merge_metadata(re3data_meta, 're3data')
        self.merge_metadata(fairsharing_meta, 'fairsharing')

        self.logger.info("--- Finished Registry Harvesting ---")

    def harmonize(self):
        h = RepositoryHarmonizer(self.catalog_url)
        harmonized_info = h.harmonize()

    def harvest_self_hosted_metadata(self):
        """
        Harvests metadata directly from the repository landing page.
        """
        if not self.catalog_html or not self.metadata_helper:
            self.logger.error('Cannot perform self-hosted harvest; initial fetch failed.')
            return
        
        self.logger.info("--- Starting Self-Hosted Harvesting ---")
        mode = 'simple'
        try:
            self.merge_metadata(self.metadata_helper.get_embedded_jsonld_metadata(mode), 'embedded_jsonld')

            self.merge_metadata(self.metadata_helper.get_html_meta_tags_metadata(), 'meta_tags')
            self.metadata_helper.signposting_helper.logger.info("Trying to find metadata using signposting links")
            signposting_links = self.metadata_helper.signposting_helper.get_links('describedby', 'application/ld+json')
            if not signposting_links:
                self.metadata_helper.signposting_helper.logger.warning("No signposting links found")
            for link in signposting_links:
                self.merge_metadata(self.metadata_helper.get_linked_jsonld_metadata(link.get('link'), mode), 'linked_jsonld')
            self.merge_metadata(self.metadata_helper.get_fairicat_metadata(), 'fairicat_services')
            self.merge_metadata(self.metadata_helper.get_feed_metadata(), 'feed_services')
            self.merge_metadata(self.metadata_helper.get_sitemap_service_metadata(), 'sitemap_service')
            self.logger.info("--- Finished Self-Hosted Harvesting ---")
        except Exception as e:
            self.logger.error(f"An error occurred during self-hosted harvest: {e}")

    def export_and_save(self, save=False):
        """
        Exports harvested metadata to DCAT JSON-LD.
        It uses the MetadataHelper export method which is based on JMESPATH see: JMESPATHQueries.py
        Some additional metadata is added here to the resulting

        :param save bool , indicates if the record shall be saved or not (in FUSEKI).
        """
        self.logger.info("--- Starting Export ---")

        final_records = []
        if not self.metadata:
            self.logger.warning("No metadata was harvested, nothing to export.")
            return final_records

        for m in self.metadata:
            metadata_chunk = m.get('metadata')
            source = m.get('source')
            if not metadata_chunk:
                continue

            if  metadata_chunk.get('services'):
                if isinstance(metadata_chunk['services'], dict):
                    metadata_chunk['services'] =  list(metadata_chunk['services'].values())
            if self.metadata_helper:
                export_record = self.metadata_helper.export(metadata_chunk)
                primary_topic = export_record.get('foaf:primaryTopic')
                #this would ignore feed metadata etc which have no repo info per se
                if primary_topic:
                    now = datetime.now()
                    date_time = now.strftime("%Y-%m-%dT%H:%M:%S")
                    graph_id = f'eden://harvester/{source}/{self.catalog_url}'

                    export_record['@id'] = graph_id
                    export_record['dct:issued'] = date_time

                    if 'prov:wasGeneratedBy' in export_record:
                        export_record['prov:wasGeneratedBy']['prov:startedAtTime'] = date_time
                        export_record['prov:wasGeneratedBy']['prov:name'] = self.extractors.get(source, "Unknown Harvester")
                        export_record['prov:wasGeneratedBy']['@id'] = f'eden://harvester/{source}'

                    if 'foaf:primaryTopic' in export_record:
                         export_record['foaf:primaryTopic']['@id'] = self.catalog_url

                    final_records.append(export_record)
                    self.logger.info(f"Successfully processed record from source: {source}")
                    ######################## saving to FUSEKI #######################
                    if save:
                        json_ld_str =json.dumps(export_record)
                        g = Graph()
                        g.parse(data=json_ld_str, format='json-ld')
                        counted_triples = len(g)

                        saved_triples = self.fuseki.save(graph_id, json_ld_str)

                        if saved_triples != None:
                            if saved_triples < counted_triples:
                                self.logger.warning(f"FUSEKI import might be incomplete: Saved {saved_triples} but counted {counted_triples} triples.")
                else:
                     self.logger.info(f"Skipping export for source '{source}': No meaningful data to map.")

        self.logger.info("--- Finished Export ---")
        return final_records

