import os

import requests
from requests.auth import HTTPBasicAuth

from repo_harvester_server.config import FUSEKI_PATH
from repo_harvester_server.helper.SPARQLQueries import GET_ALL_GRAPHS
from SPARQLWrapper import SPARQLWrapper, JSON

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
# some methods to check and clean the FUSEKI store

class FUSEKIHelper:
    logger = logging.getLogger('FUSEKIHelper')

    def __init__(self):
        self.FUSEKI_USERNAME = os.environ.get('FUSEKI_USERNAME')
        self.FUSEKI_PASSWORD = os.environ.get('FUSEKI_PASSWORD')


    def get_repo_graphs(self, repouri):
        """
        Retrieve all named graphs from FUSEKI.Except harmonized graph
        """

        sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/sparql'))
        if self.FUSEKI_USERNAME and self.FUSEKI_PASSWORD:
            sparql.setCredentials(self.FUSEKI_USERNAME, self.FUSEKI_PASSWORD)

        # Step1: use SPARQL query to get all graphs for a given catalog/repo
        sparql.setQuery(f"""
            SELECT DISTINCT ?g
            WHERE {{
              GRAPH ?g {{ ?s ?p ?o }}
              FILTER(CONTAINS(STR(?g), "{repouri}"))
              FILTER(!CONTAINS(STR(?g), "eden://harvester/harmonized/"))
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
                auth = (self.FUSEKI_USERNAME, self.FUSEKI_PASSWORD)
                r = requests.get(str(FUSEKI_PATH), params=params, headers=headers, auth=auth)
                all_graphs[g_uri]= r.json()
        except Exception as e:
            self.logger.error('FUSEKI (while trying to SPARQL) Error: '+str(e))

        return all_graphs

    def get_all_graphids(self):
        sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/query'))
        sparql.setCredentials(self.FUSEKI_USERNAME, self.FUSEKI_PASSWORD)
        sparql.setQuery(GET_ALL_GRAPHS)
        sparql.setReturnFormat('json')
        results = sparql.query().convert()
        graph_list = [r['g']['value'] for r in results["results"]["bindings"]]
        return graph_list

    def save(self, graph_uri, graph_jsonld):
        """
        Saves a named graph in a JENA FUSEKI triple store
        :param graph_uri:
        :param graph_jsonld:
        :return: int, number of saved triples
        """
        self.logger.info("Attempting to save graph in FUSEKI : "+ str(graph_uri))
        count = None
        try:
            headers = {
                "Content-Type": "application/ld+json"
            }
            # Use graph store protocol
            response = requests.put(
                FUSEKI_PATH,
                params={"graph": graph_uri},
                data=graph_jsonld,
                headers=headers,
                auth=HTTPBasicAuth(self.FUSEKI_USERNAME, self.FUSEKI_PASSWORD)
            )
            if response.status_code not in [200, 201]:
                if response.status_code == 401:
                    self.logger.warning("RepositoryHarvester is not authorized to access FUSEKI. Please check your OS env variables: FUSEKI_USER, FUSEKI_PASSWORD.")
                self.logger.error(f"FUSEKI error, status code: {response.status_code}")
            else:
                self.logger.info("Successfully saved graph in FUSEKI : " + str(graph_uri))
                count = response.json().get('count')
        except requests.exceptions.ConnectionError as e:
            self.logger.error("FUSEKI server not available / connection failed: "+str(e))
        except Exception as e:
            self.logger.error(f"FUSEKI error occured while saving graph: {e}")
        return count

    def reset_index(self, graph_list):
        sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/update'))
        sparql.setCredentials(self.FUSEKI_USERNAME, self.FUSEKI_PASSWORD)
        for g in graph_list:
            # DROP GRAPH is safe even if the graph is already empty
            drop_query = f"DROP GRAPH <{g}>"
            sparql.setQuery(drop_query)
            sparql.query()  # Executes the update
            print(f"Dropped graph: {g}")

        print("All named graphs deleted.")



'''f = FUSEKIHelper()
all_graphs = f.get_all_graphids()
print(all_graphs)
f.reset_index(all_graphs)'''