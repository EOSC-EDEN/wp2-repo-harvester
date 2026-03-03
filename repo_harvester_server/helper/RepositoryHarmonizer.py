import json
import logging
import os
from collections import Counter

import jmespath
import requests


from repo_harvester_server.config import FUSEKI_PATH
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper
from repo_harvester_server.helper.JMESPATHQueries import DCAT_EXPORT_QUERY
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.GraphHelper import JSONGraph

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)


class RepositoryHarmonizer:
    logger = logging.getLogger('RepositoryHarmonizer')

    def __init__(self, repouri):
        self.repouri = repouri
        self.fuseki = FUSEKIHelper()

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
        def clean_value(value):
            if isinstance(value, str):
                return value
            elif isinstance(value, dict):
                if list(value.keys()) == ['@id']:
                    return value['@id']
            else:
                return str(value)



        combined = {}
        basic_props = ['title', 'description', 'publisher', 'contact']

        self.logger.info('--- Starting Harmonization ---')

        # Build combined dict from all graphs
        all_graphs = self.fuseki.get_repo_graphs(self.repouri)
        if not all_graphs:
            self.logger.error('Could not find any data related to this repo in FUSEKI: {}'.format(str(self.repouri)) )
            return False
        else:
            self.logger.info('Found {} raw records related to this repo in FUSEKI: {}'.format(str(len(all_graphs.items())),str(self.repouri)))

        for gid, g in all_graphs.items():
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
                values = [clean_value(vl.get("value")) for vl in v]
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
        merged_uri = f"eden://harvester/harmonized/"+str(self.repouri)
        merged_catalog_dcat["@id"] = merged_uri

        # save harmonized record in FUSEKI
        self.fuseki.save(merged_uri,json.dumps(merged_catalog_dcat))

        self.logger.info('--- Finished Harmonization ---')

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


'''Usage:
h = RepositoryHarmonizer(catalog_id)
catalog_info = h.harmonize()
print(json.dumps(catalog_info , indent=2))'''

