import json
import logging
from datetime import datetime

from rdflib import Graph

from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.RepositoryHarmonizer import RepositoryHarmonizer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


class DarkArchiveHarvester:
    """
    Harvests metadata for dark archives — repositories with no public access
    that are discoverable only via the re3data registry.

    Unlike RepositoryHarvester, this class does not require a live repository URL.
    Discovery uses the re3data databaseAccess=closed filter. The re3data page URL
    (https://www.re3data.org/repository/{id}) is used as the canonical identifier
    for FUSEKI storage and harmonization.

    Usage:
        h = DarkArchiveHarvester()
        records = h.harvest()               # auto-discover all via re3data filter
        records = h.harvest(['r3d100013353', 'r3d100014761'])  # specific IDs only
    """
    logger = logging.getLogger('DarkArchiveHarvester')

    RE3DATA_REPO_BASE = "https://www.re3data.org/repository/"

    def __init__(self):
        self.fuseki = FUSEKIHelper()
        self.re3data = Re3DataHarvester()
        self.metadata_helper = MetadataHelper()

    def harvest(self, re3data_ids=None):
        """
        Discovers and harvests dark archives.

        :param re3data_ids: Optional list of specific re3data IDs to harvest.
                            If None, auto-discovers via the re3data databaseAccess=closed filter.
        :returns: List of exported DCAT JSON-LD records.
        """
        if re3data_ids:
            self.logger.info(f"Harvesting {len(re3data_ids)} specified dark archive IDs")
            candidates = []
            for rid in re3data_ids:
                metadata = self.re3data.harvest_by_id(rid)
                if metadata:
                    candidates.append({'re3data_id': rid, 'metadata': metadata})
                else:
                    self.logger.warning(f"Could not fetch metadata for re3data ID: {rid}")
        else:
            candidates = self.re3data.discover_dark_archives()

        exported = []
        for item in candidates:
            record = self._export_and_save(item['re3data_id'], item['metadata'])
            if record:
                exported.append(record)
                self._harmonize(item['re3data_id'])

        self.logger.info(f"Dark archive harvest complete: {len(exported)} records saved")
        return exported

    def _export_and_save(self, re3data_id, metadata):
        catalog_url = f"{self.RE3DATA_REPO_BASE}{re3data_id}"
        graph_id = f"eden://harvester/re3data/{catalog_url}"

        dcat = self.metadata_helper.export(metadata)
        if not dcat or not dcat.get('foaf:primaryTopic'):
            self.logger.warning(f"No exportable DCAT data for {re3data_id}")
            return None

        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        dcat['@id'] = graph_id
        dcat['dct:issued'] = now

        if 'prov:wasGeneratedBy' in dcat:
            dcat['prov:wasGeneratedBy']['prov:startedAtTime'] = now
            dcat['prov:wasGeneratedBy']['prov:name'] = 're3data.org Dark Archive Discovery'
            dcat['prov:wasGeneratedBy']['@id'] = 'eden://harvester/re3data'

        primary_topic = dcat['foaf:primaryTopic']
        primary_topic['@id'] = catalog_url
        primary_topic['dct:accessRights'] = 'closed'

        json_str = json.dumps(dcat)
        g = Graph()
        g.parse(data=json_str, format='json-ld')
        counted_triples = len(g)
        saved_triples = self.fuseki.save(graph_id, json_str)

        if saved_triples is not None and saved_triples < counted_triples:
            self.logger.warning(
                f"FUSEKI import may be incomplete for {re3data_id}: "
                f"saved {saved_triples}, counted {counted_triples} triples"
            )
        else:
            self.logger.info(f"Saved dark archive record for {re3data_id} ({catalog_url})")

        return dcat

    def _harmonize(self, re3data_id):
        catalog_url = f"{self.RE3DATA_REPO_BASE}{re3data_id}"
        try:
            h = RepositoryHarmonizer(catalog_url)
            h.harmonize()
        except Exception as e:
            self.logger.error(f"Harmonization failed for {re3data_id}: {e}")
