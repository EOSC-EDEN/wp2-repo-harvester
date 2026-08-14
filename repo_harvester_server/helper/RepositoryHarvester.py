import json
import os
from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import logging

from rdflib import Graph

from repo_harvester_server import config
from repo_harvester_server.helper.HarvestSession import build_session
from repo_harvester_server.helper.RepositoryHarmonizer import RepositoryHarmonizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.RegistryHTTP import RegistryUnavailableError
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper
from repo_harvester_server.helper.ServiceInfoHelper import ServiceInfoHelper

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

    # The registries this harvester knows how to consult. Used to work out what
    # a configuration has switched *off*, which the demo page reports separately
    # from what it tried and failed to reach.
    REGISTRY_NAMES = ('re3data', 'fairsharing')


    def __init__(self, catalog_url, run_id=None, re3data_harvester=None,
                 fairsharing_harvester=None, repository_name=None, session=None,
                 enabled_registries=None, persist=None):
        self.catalog_url = catalog_url
        # The repository's real name, when the caller knows it. A registry
        # search by name beats one by a name guessed from the hostname, which
        # is how a batch ended up asking FAIRsharing about 'www' and 'data'.
        self.repository_name = repository_name
        # One validation run per harvester unless the caller shares one across
        # repositories (harvest_all does; a single API request is its own run).
        self.run_id = run_id or ServiceInfoHelper.mint_run_id()
        # Registry harvesters may be shared across a batch so one FAIRsharing
        # sign-in covers every repository; a lone API request builds its own.
        self.re3data_harvester = re3data_harvester
        self.fairsharing_harvester = fairsharing_harvester
        self.catalog_html = None
        self.metadata = []
        self.dcats = []
        self.metadata_helper = None
        self.catalog_ids = [self.catalog_url]
        # Per-stage outcome flags, filled in by harvest()/harmonize(). A repo
        # can legitimately be harvested but not harmonized (empty store on a
        # first run), so callers report the stages separately.
        self.harmonized_ok = False
        self.persisted_ok = False
        # Registries that could not be consulted for this repository (rate
        # limited, unreachable). The repo still counts as harvested, but its
        # record is incomplete and the run must say so.
        self.degraded_sources = []

        # What this harvester is configured to do. A "mode" belongs to the
        # instance, not to the process: one deployment serves interactive
        # requests with no credentials while a batch on another machine
        # persists everything.
        self.enabled_registries = (
            [str(name).strip().lower() for name in enabled_registries]
            if enabled_registries is not None
            else list(config.ENABLED_REGISTRIES)
        )
        self.disabled_registries = [
            name for name in self.REGISTRY_NAMES if name not in self.enabled_registries
        ]
        self.persist = config.PERSISTENCE_ENABLED if persist is None else bool(persist)

        self.check_environment_variables()

        self.service_helper = ServiceInfoHelper()

        self.fuseki = FUSEKIHelper()

        # One guarded session for the landing page and everything the page then
        # points us at. It applies the polite User-Agent, a default timeout, and
        # the address checks - on the initial fetch and on each redirect hop.
        self.session = session or build_session()

        if not str(self.catalog_url).startswith('http'):
            self.logger.error("Invalid repo URI: %s", self.catalog_url)

        try:
            response = self.session.get(self.catalog_url, timeout=10)
            response.raise_for_status()
            #using the canonical url to identify the resource
            if response.url != self.catalog_url:
                self.logger.info("Redirected to URI: %s , so will use this as the canonical URL", response.url)
                self.catalog_ids.append(response.url)
                self.catalog_url = response.url
            self.catalog_html = response.text
            self.catalog_header = response.headers
            self.metadata_helper = MetadataHelper(
                self.catalog_url, self.catalog_html, self.catalog_header,
                session=self.session,
            )
            self.logger.info('Catalog URL harvested: '+ self.catalog_url)
        except requests.exceptions.RequestException as e:
            self.logger.error("Failed to fetch URI: %s", self.catalog_url)


    def check_environment_variables(self):
        """Report only the credentials this harvester's configuration needs.

        A blanket check logs four errors per request on a deployment that
        deliberately has no registry credentials and no triple store, which
        makes a healthy service look broken.
        """
        all_variables_available = True
        if 'fairsharing' in self.enabled_registries:
            if not os.environ.get('FAIRSHARING_USERNAME'):
                self.logger.error("FAIRSHARING_USERNAME (OS env variable) not set – please define it before running")
                all_variables_available = False
            if not os.environ.get('FAIRSHARING_PASSWORD'):
                self.logger.error("FAIRSHARING_PASSWORD (OS env variable) not set – please define it before running")
                all_variables_available = False
        if self.persist:
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
        harmonized = self.harmonize()
        if not harmonized:
            self.logger.warning("Harmonization produced no record for %s", self.catalog_url)
        elif not self.persisted_ok:
            self.logger.warning("Harmonized record for %s was NOT persisted to FUSEKI", self.catalog_url)
        return harvested_records

    def _try_registry(self, registry, call, *args):
        """Run one registry call, turning an unavailable registry into a
        recorded degradation instead of a failed repository.

        Skips the call outright if this registry already failed for this
        repository — once FAIRsharing is rate-limiting us, the cross-registry
        bridge calls below are just more doomed requests.
        """
        if registry in self.degraded_sources:
            self.logger.info(
                "Skipping %s: already unavailable for %s this run",
                registry, self.catalog_url,
            )
            return None
        try:
            return call(*args)
        except RegistryUnavailableError as e:
            self.logger.warning(
                "%s - continuing without its metadata for %s", e, self.catalog_url
            )
            self.degraded_sources.append(registry)
            return None

    def harvest_registry_metadata(self):
        """
        Orchestrates harvesting from external registries with cross-referencing.
        """
        self.logger.info("--- Starting Registry Harvesting ---")

        re3data_harvester = self.re3data_harvester or Re3DataHarvester()
        fairsharing_harvester = self.fairsharing_harvester or FAIRsharingHarvester()

        re3data_meta = None
        fairsharing_meta = None

        # 1. First pass on re3data
        re3_urls = '|'.join(self.catalog_ids) # in case more than one URL is know (e.g. via redirect)
        re3data_meta = self._try_registry('re3data', re3data_harvester.harvest, re3_urls)

        # 2. Harvest FAIRsharing, using re3data's findings if available
        fairsharing_id = None
        if re3data_meta:
            for identifier in re3data_meta.get('identifier', []):
                # Case-insensitive check for FAIRsharing ID
                if 'fairsharing' in identifier.lower():
                    fairsharing_id = identifier
                    break

        if fairsharing_id:
            fairsharing_meta = self._try_registry(
                'fairsharing', fairsharing_harvester.harvest_by_id, fairsharing_id
            )
        else:
            fairsharing_meta = self._try_registry(
                'fairsharing', fairsharing_harvester.harvest,
                self.catalog_url, self.repository_name,
            )

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
                re3data_meta = self._try_registry(
                    're3data', re3data_harvester.harvest_by_id, re3data_id
                )
            # Fallback: Try bridging by name if no ID found
            elif fairsharing_meta.get('title'):
                self.logger.info(f"Bridging to re3data by name: {fairsharing_meta.get('title')}")
                re3data_meta = self._try_registry(
                    're3data', re3data_harvester.harvest_by_name,
                    fairsharing_meta.get('title')
                )

        # 4. Merge all collected metadata
        self.merge_metadata(re3data_meta, 're3data')
        self.merge_metadata(fairsharing_meta, 'fairsharing')

        self.logger.info("--- Finished Registry Harvesting ---")

    def harmonize(self):
        h = RepositoryHarmonizer(self.catalog_url, run_id=self.run_id)
        harmonized_info = h.harmonize()
        self.harmonized_ok = bool(harmonized_info)
        self.persisted_ok = h.persisted
        return harmonized_info

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
            self.merge_metadata(self.metadata_helper.get_opensearch_metadata(), 'open_search')
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

        # export() is a pure DCAT mapping over the chunk it is handed; it needs
        # no landing page. Registry metadata arrives even when the initial fetch
        # failed, so fall back to a page-less helper rather than dropping those
        # records silently - which is how repositories with a verified re3data
        # and FAIRsharing record still reported 'Metadata: No, Services: 0'.
        #
        # Constructed without a URL on purpose, as RepositoryHarmonizer does.
        # Passing one makes SignPostingHelper fetch the page with no timeout, so
        # exporting a repository whose landing page is already known to be dead
        # would hang and then fail the repository - AgroPortal did exactly that
        # (agroportal.lirmm.fr -> agroportal.eu, connect timeout) in the
        # 2026-08-13 batch.
        mapper = self.metadata_helper or MetadataHelper()

        for m in self.metadata:
            metadata_chunk = m.get('metadata')
            source = m.get('source')
            if not metadata_chunk:
                continue

            if  metadata_chunk.get('services'):
                if isinstance(metadata_chunk['services'], dict):
                    metadata_chunk['services'] =  list(metadata_chunk['services'].values())
            export_record = mapper.export(metadata_chunk)
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
                    export_record['prov:wasGeneratedBy']['rdfs:label'] = self.extractors.get(source, "Unknown Harvester")
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

