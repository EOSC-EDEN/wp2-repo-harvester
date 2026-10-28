#!/usr/bin/env python3
"""
Harmonise every harvested repository again from the graphs in FUSEKI, without harvesting.
Run it after the KB's source patterns change.

Usage:
    python harmonize_all.py
"""

import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper
from repo_harvester_server.helper.RawGraph import RAW_GRAPH_PREFIX
from repo_harvester_server.helper.RepositoryHarmonizer import RepositoryHarmonizer
from repo_harvester_server.helper.ServiceInfoHelper import ServiceInfoHelper

SOURCE_GRAPH_PREFIX = 'eden://harvester/'
HARMONIZED_GRAPH_PREFIX = 'eden://harvester/harmonized/'


def repository_urls(graph_ids):
    """The repositories that have source graphs, sorted and without duplicates."""
    urls = {graph_id[len(SOURCE_GRAPH_PREFIX):].partition('/')[2] for graph_id in graph_ids
            if graph_id.startswith(SOURCE_GRAPH_PREFIX)
            and not graph_id.startswith((HARMONIZED_GRAPH_PREFIX, RAW_GRAPH_PREFIX))}
    return sorted(url for url in urls if url)


def main():
    urls = repository_urls(FUSEKIHelper().get_all_graphids())
    # One validation run for the batch, as in harvest_all.
    run_id = ServiceInfoHelper.mint_run_id()
    harmonized = persisted = 0
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        harmonizer = RepositoryHarmonizer(url, run_id=run_id)
        try:
            harmonized += bool(harmonizer.harmonize())
        except Exception as e:
            print(f"    FAILED: {e}")
        persisted += harmonizer.persisted
    print(f"Harmonized: {harmonized} of {len(urls)}, persisted to FUSEKI: {persisted}")
    return 0 if persisted == len(urls) else 1


if __name__ == "__main__":
    sys.exit(main())
