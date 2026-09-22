#!/usr/bin/env python3
"""Save harmonized graphs from FUSEKI as Turtle, one file per repository.

Usage:
    python export_ttl.py                           # list what the store holds
    python export_ttl.py https://www.pangaea.de/   # one repository
    python export_ttl.py --all                     # every harmonized graph

Read-only. Files land in output/ttl. Turtle rather than the JSON-LD the API
returns because it reads better in an editor; the graph is the same.
"""
import argparse
import csv
import os
import sys

import requests
from requests.auth import HTTPBasicAuth

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from repo_harvester_server.config import FUSEKI_PATH

OUTPUT_DIR = os.path.join('output', 'ttl')
HARMONIZED_PREFIX = 'eden://harvester/harmonized/'
LIST_QUERY = f"""
SELECT DISTINCT ?g WHERE {{
  GRAPH ?g {{ ?s ?p ?o }}
  FILTER(STRSTARTS(STR(?g), "{HARMONIZED_PREFIX}"))
}}
"""


def credentials():
    user = os.environ.get('FUSEKI_USERNAME')
    password = os.environ.get('FUSEKI_PASSWORD')
    if not user or not password:
        sys.exit('FUSEKI credentials are not set: define the FUSEKI_USERNAME and '
                 f'FUSEKI_PASSWORD environment variables before running '
                 f'(endpoint: {FUSEKI_PATH}).')
    return HTTPBasicAuth(user, password)


def graph_uri_for(argument):
    """Accept either the repository URL or the full harmonized graph URI."""
    if argument.startswith(HARMONIZED_PREFIX):
        return argument
    return HARMONIZED_PREFIX + argument


def filename_for(graph_uri):
    repo_url = graph_uri[len(HARMONIZED_PREFIX):] if graph_uri.startswith(HARMONIZED_PREFIX) else graph_uri
    host_and_path = repo_url.split('://', 1)[-1].strip('/')
    safe = ''.join(c if c.isalnum() or c in '.-' else '_' for c in host_and_path)
    return (safe or 'unnamed_repo') + '.ttl'


def list_graphs(auth):
    response = requests.get(str(FUSEKI_PATH).replace('/data', '/query'),
                            params={'query': LIST_QUERY},
                            headers={'Accept': 'text/csv'}, auth=auth, timeout=30)
    response.raise_for_status()
    rows = list(csv.reader(response.text.splitlines()))
    return sorted(row[0] for row in rows[1:] if row and row[0])


def save_graph(graph_uri, auth, output_dir):
    response = requests.get(str(FUSEKI_PATH), params={'graph': graph_uri},
                            headers={'Accept': 'text/turtle'}, auth=auth, timeout=60)
    if response.status_code == 404:
        print(f'  not in the store: {graph_uri}')
        return None
    response.raise_for_status()
    path = os.path.join(output_dir, filename_for(graph_uri))
    with open(path, 'w', encoding='utf-8') as out:
        out.write(response.text)
    print(f'  {path}')
    return path


def self_check():
    assert filename_for(HARMONIZED_PREFIX + 'https://www.pangaea.de/') == 'www.pangaea.de.ttl'
    assert filename_for(HARMONIZED_PREFIX + 'http://data.crossda.hr/?q=x') == 'data.crossda.hr__q_x.ttl'
    assert filename_for(HARMONIZED_PREFIX) == 'unnamed_repo.ttl'
    assert graph_uri_for('https://www.pangaea.de/') == HARMONIZED_PREFIX + 'https://www.pangaea.de/'
    assert graph_uri_for(HARMONIZED_PREFIX + 'x') == HARMONIZED_PREFIX + 'x'
    print('self-check OK')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('urls', nargs='*', help='Repository landing page URLs')
    parser.add_argument('--all', action='store_true', help='Export every harmonized graph')
    parser.add_argument('--output-dir', default=OUTPUT_DIR,
                        help=f'Where the .ttl files go (default: {OUTPUT_DIR})')
    parser.add_argument('--self-check', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.self_check:
        self_check()
        return

    auth = credentials()

    if not args.urls and not args.all:
        graphs = list_graphs(auth)
        print(f'{len(graphs)} harmonized graphs in {FUSEKI_PATH}:')
        for graph in graphs:
            print(f'  {graph[len(HARMONIZED_PREFIX):]}')
        print('\nExport one with: python export_ttl.py <repository URL>')
        return

    graphs = list_graphs(auth) if args.all else [graph_uri_for(url) for url in args.urls]
    os.makedirs(args.output_dir, exist_ok=True)
    print(f'Writing {len(graphs)} graph(s) to {args.output_dir}:')
    saved = [g for g in graphs if save_graph(g, auth, args.output_dir)]

    if len(saved) != len(graphs):
        sys.exit(f'{len(graphs) - len(saved)} of {len(graphs)} graph(s) could not be exported. '
                 'The repository URL must match the harvested one exactly, trailing slash included.')


if __name__ == '__main__':
    main()
