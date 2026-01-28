# Apache Jena Fuseki Setup

Optional triple store for SPARQL queries over harvested metadata.

## Install

```bash
# Install outside the repo
mkdir -p ~/tools && cd ~/tools

# Download (check https://jena.apache.org/download/ for latest)
wget https://dlcdn.apache.org/jena/binaries/apache-jena-fuseki-5.6.0.tar.gz
tar -xzf apache-jena-fuseki-5.6.0.tar.gz
cd apache-jena-fuseki-5.6.0
```

## Run

```bash
# Persistent storage (recommended)
mkdir -p ./data
./fuseki-server --update --tdb2 --loc=./data /service_registry_store

# Or in-memory (data lost on restart)
./fuseki-server --update --mem /service_registry_store
```

The `--update` flag enables the Graph Store Protocol for writing.

## Endpoints

| URL                                                 | Purpose         |
| --------------------------------------------------- | --------------- |
| http://localhost:3030/                              | Admin UI        |
| http://localhost:3030/service_registry_store/sparql | SPARQL endpoint |
| http://localhost:3030/service_registry_store/data   | Graph Store     |

The harvester auto-saves to Fuseki when running. Configure endpoint in `repo_harvester_server/config.py`.

## Named Graphs

Data is stored in named graphs, not the default graph. Pattern:

```bash
eden://harvester/{source}/{repository_url}
```

Example: `eden://harvester/re3data/https://pangaea.de/`

## Example Queries

**List all harvested repositories:**

```sparql
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?graph ?repo ?title WHERE {
  GRAPH ?graph {
    ?repo a dcat:Catalog ;
          dct:title ?title .
  }
}
```

**List all named graphs:**
```sparql
SELECT DISTINCT ?g WHERE {
  GRAPH ?g { ?s ?p ?o }
}
```

**Find all services across repositories:**
```sparql
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?repoTitle ?serviceTitle ?endpoint WHERE {
  GRAPH ?g {
    ?repo a dcat:Catalog ;
          dct:title ?repoTitle ;
          dcat:service ?service .
    ?service dct:title ?serviceTitle ;
             dcat:endpointURL ?endpoint .
  }
}
```

Run queries at: http://localhost:3030/#/dataset/service_registry_store/query
