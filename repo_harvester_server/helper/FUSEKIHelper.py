import os

from SPARQLWrapper import SPARQLWrapper
from repo_harvester_server.config import FUSEKI_PATH
from repo_harvester_server.helper.SPARQLQueries import GET_ALL_GRAPHS

# some methods to check and clean the FUSEKI store

def get_all_graphids():
    FUSEKI_USERNAME = os.environ.get('FUSEKI_USERNAME')
    FUSEKI_PASSWORD = os.environ.get('FUSEKI_PASSWORD')
    sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/query'))
    sparql.setCredentials(FUSEKI_USERNAME, FUSEKI_PASSWORD)
    sparql.setQuery(GET_ALL_GRAPHS)
    sparql.setReturnFormat('json')
    results = sparql.query().convert()
    graph_list = [r['g']['value'] for r in results["results"]["bindings"]]
    return graph_list

def reset_index(graph_list):
    FUSEKI_USERNAME = os.environ.get('FUSEKI_USERNAME')
    FUSEKI_PASSWORD = os.environ.get('FUSEKI_PASSWORD')
    sparql = SPARQLWrapper(str(FUSEKI_PATH).replace('/data', '/update'))
    sparql.setCredentials(FUSEKI_USERNAME, FUSEKI_PASSWORD)
    for g in graph_list:
        # DROP GRAPH is safe even if the graph is already empty
        drop_query = f"DROP GRAPH <{g}>"
        sparql.setQuery(drop_query)
        sparql.query()  # Executes the update
        print(f"Dropped graph: {g}")

    print("All named graphs deleted.")


    #drops all named graphs
    #def reset(self):

all_graphs = get_all_graphids()
print(all_graphs)
#reset_index(all_graphs)