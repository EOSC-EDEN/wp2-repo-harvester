import json
import logging
import os
from collections import Counter

import jmespath
import requests

from SPARQLWrapper import SPARQLWrapper, JSON

from repo_harvester_server.config import FUSEKI_PATH
from repo_harvester_server.helper.JMESPATHQueries import DCAT_EXPORT_QUERY
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.GraphHelper import JSONGraph

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


class RepositoryHarmonizer:
    logger = logging.getLogger('RepositoryHarvester')

    def __init__(self, repouri):
        self.repouri = repouri

    def clean_none(self, obj):
        """
        Recursively:
          - Remove keys with value None from dictionaries
          - Remove None entries from lists
          - Deduplicate lists
        """
        try:
            if isinstance(obj, dict):
                return {
                    k: self.clean_none(v)
                    for k, v in obj.items()
                    if v is not None
                }
            elif isinstance(obj, list):
                cleaned_list = [self.clean_none(item) for item in obj if item is not None]

                # Deduplicate while preserving order for hashable items
                seen = set()
                deduped = []
                for item in cleaned_list:
                    # Only deduplicate hashable items
                    if isinstance(item, (str, int, float, bool)):
                        if item not in seen:
                            deduped.append(item)
                            seen.add(item)
                    else:
                        # Non-hashable items (dicts, lists) are added as-is
                        deduped.append(item)
                return deduped
            else:
                return obj
        except Exception as e:
            return obj

    def harmonize(self):
        """
        actually THE harmonize method which should be called to perform the harmonization
        """
        combined = {}
        basic_props = ['title', 'description', 'publisher', 'contact']

        # Build combined dict from all graphs
        for gid, g in self.get_graphs().items():
            mh = MetadataHelper()
            rg = JSONGraph()
            rg.parse(json.dumps(g), gid)
            catalog_graph = jmespath.search('primaryTopic', rg.jsonld)
            catalog_dict = mh.get_jsonld_metadata_simple(json.dumps(catalog_graph), self.repouri)

            src = gid.split('/')[3]
            for k, v in catalog_dict.items():
                items = v if isinstance(v, list) else [v]
                combined.setdefault(k, []).extend(
                    {'source': src, 'value': item} for item in items
                )

        catalog_info = {"id": self.repouri, "hadPrimarySource": []}
        service_info = []
        policy_info = []

        for k, v in combined.items():
            sources = [f'eden://harvester/{s.get('source')}/{self.repouri}' for s in v if s.get('source')]
            catalog_info['hadPrimarySource'].extend(sources)
            if k in basic_props:
                catalog_info[k], source = self.get_best_records(v)
            elif k == 'services':
                service_info.extend(v)
            elif k == 'policies':
                policy_info.extend(v)
            else:
                values = [vl.get("value") for vl in v]
                catalog_info[k] = list(set(catalog_info.get(k, []) + values))

        if isinstance(catalog_info.get("subject"), list):
            catalog_info["subject"] = list({kw.lower() for kw in catalog_info["subject"]})

        catalog_info["hadPrimarySource"] = list(set(catalog_info["hadPrimarySource"]))
        catalog_info["policies"] = self.merge(policy_info, merge_fields=["title", "type"],
                                              key_field="policy_uri", catalog_id=self.repouri)
        catalog_info["services"] = self.merge(service_info,
                                              merge_fields=["title", "type", "conforms_to", "output_format"],
                                              key_field="endpoint_uri", catalog_id=self.repouri)
        merged_catalog_dcat = self.clean_none(jmespath.search(DCAT_EXPORT_QUERY, catalog_info))

        if merged_catalog_dcat.get("prov:wasGeneratedBy"):
            merged_catalog_dcat["prov:wasGeneratedBy"]["prov:name"] = 'Metadata harmonizing activity'
        merged_catalog_dcat["@id"] = "eden://harvester/harmonized/"+str(self.repouri)

        return merged_catalog_dcat

    def merge(self, records, merge_fields, key_field, catalog_id):
        """
        Save merging of lists and dicts etc within a graph
        """
        def as_list(x):
            return x if isinstance(x, list) else [x] if x else []

        def clean_value(x):
            if isinstance(x, list):
                x = list(set(x))
                if len(x) == 1:
                    x = x[0]
            return x

        merged = {}

        for rec in records:
            val = rec["value"]
            key = val[key_field]

            source_part = rec.get("source")
            source = (
                f"eden://harvester/{source_part}/{catalog_id}"
                if source_part else None
            )

            if key not in merged:
                new_val = dict(val)
                for f in merge_fields:
                    new_val[f] = as_list(val.get(f))
                new_val["hadPrimarySource"] = as_list(source)
                merged[key] = new_val
                continue

            m = merged[key]

            for f in merge_fields:
                m[f].extend(as_list(val.get(f)))

            if source:
                m["hadPrimarySource"].append(source)

        # Final cleanup: dedupe + flatten
        return [
            {k: clean_value(v) for k, v in item.items()}
            for item in merged.values()
        ]

    def get_graphs(self):
        """
        Retrieve all named graphs from FUSEKI.
        """
        FUSEKI_USERNAME = os.environ.get('FUSEKI_USERNAME')
        FUSEKI_PASSWORD = os.environ.get('FUSEKI_PASSWORD')

        sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/sparql'))
        if FUSEKI_USERNAME and FUSEKI_PASSWORD:
            sparql.setCredentials(FUSEKI_USERNAME, FUSEKI_PASSWORD)

        # Step1: use SPARQL query to get all graphs for a given catalog/repo
        sparql.setQuery(f"""
            SELECT DISTINCT ?g
            WHERE {{
              GRAPH ?g {{ ?s ?p ?o }}
              FILTER(CONTAINS(STR(?g), "{self.repouri}"))
            }}
            """)
        sparql.setReturnFormat(JSON)
        all_graphs = {}
        try:
            results = sparql.query().convert()
            graph_uris = [r['g']['value'] for r in results["results"]["bindings"]]
            # Step 2: retrieve each graph via GSP

            for g_uri in graph_uris:
                params = {"graph": g_uri}
                headers = {"Accept": "application/ld+json"}
                auth = (FUSEKI_USERNAME, FUSEKI_PASSWORD)
                r = requests.get(str(FUSEKI_PATH), params=params, headers=headers, auth=auth)
                all_graphs[g_uri]= r.json()
        except Exception as e:
            self.logger.error('FUSEKI (while trying to SPARQL) Error: '+str(e))

        return all_graphs

    def get_best_records(self, records, size_weight=1.0, source_weight=0.5, freq_weight=1.0):
        """
        Sort records by combined score, deduplicate, and attach the score to each record.
        """
        source_priority = {'re3data': 0, 'fairsharing': 1}

        # Helper to get frequency key and size
        def get_freq_and_size(value):
            if isinstance(value, dict):
                freq_key = str(value)
                size = sum(1 for k in value if value.get(k))
            elif isinstance(value, str):
                freq_key = value
                size = len(value)
            else:
                freq_key = str(value)
                size = 0
            return freq_key, size

        # Precompute freq keys and sizes
        precomputed = []
        for r in records:
            value = r.get('value')
            fk, sz = get_freq_and_size(value)
            precomputed.append({'record': r, 'freq_key': fk, 'size': sz})

        freq_counter = Counter(item['freq_key'] for item in precomputed)
        max_freq = max(freq_counter.values(), default=1)
        max_size = max(item['size'] for item in precomputed) if precomputed else 1
        max_rank = max(source_priority.values(), default=99)

        # Compute scores and sum per source
        source_scores = {}
        for item in precomputed:
            r = item['record']
            source = r.get('source', 'unknown')
            size_score = item['size'] / max_size if max_size else 0
            source_rank = source_priority.get(source, max_rank)
            source_score = 1 - (source_rank / max_rank)
            freq_score = freq_counter[item['freq_key']] / max_freq
            score = size_score * size_weight + source_score * source_weight + freq_score * freq_weight

            r['_score'] = score  # attach score to record

            source_scores[source] = source_scores.get(source, 0) + score

        best_source = max(source_scores, key=source_scores.get)

        best_records = [r['record']['value'] for r in precomputed if r['record'].get('source') == best_source]

        if isinstance(best_records, list):
            if len(best_records) == 1:
                best_records = best_records[0]
        return best_records, best_source

catalog_id = 'https://pangaea.de/'
#catalog_id = 'https://dans.knaw.nl/nl/social-sciences-and-humanities/'
#catalog_id = 'https://dais.sanu.ac.rs/'
h = RepositoryHarmonizer(catalog_id)


catalog_info = h.harmonize()


print(json.dumps(catalog_info , indent=2))

