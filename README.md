# EDEN WP2 Repository Harvester

This service collects, aggregates, and normalizes metadata from scientific repositories (e.g., via re3data, FAIRiCAT/Signposting, or embedded JSON-LD). It transforms the data into the official EDEN-FIDELIS JSON-LD schema for use by the Registry Frontend and ElasticSearch.

## 📂 Project Structure

* `schema/` :  The Single Source of Truth . Contains the JSON-LD Context and the "Golden Record" example.
* `repo_harvester_server/` : The Python application logic.
  * `controllers/`: API endpoint logic.
  * `helper/`: Core harvesting and parsing logic (`MetadataHelper.py`).
  * `models/`: Data objects.
* `main.py` : The entry point to run the API server.

## 🚀 Setup & Installation

### 1. Clone and Configure
```bash
# Clone the repository
git clone <repository-url>
cd wp2-repo-harvester

# Create a Virtual Environment (venv)
python3 -m venv venv
source venv/bin/activate

# Install Dependencies  
pip install -r requirements.txt

# Set the necessary OS env variables: 
* FUSEKI_USERNAME
* FUSEKI_PASSWORD
* FAIRSHARING_USERNAME
* FAIRSHARING_PASSWORD

```

### 2. Run the Harvester Server

```bash
python main.py
```

## 🌾 Harvest

Once the server is running, it acts as an API. You can harvest repositories using your browser, `curl`, or any HTTP client.

### 1. Documentation (Swagger UI)

Visit [http://localhost:8080/ui](http://localhost:8080/ui) to see the API definition and test endpoints interactively.

### 2. Harvest a single repository

Run this command in a new terminal window:

```bash
curl "http://localhost:8080/?url=https://pangaea.de"
```

* Response:  You will receive a JSON object structured according to the EDEN Schema containing the repository's title, publisher, and services.

### 3. Batch Harvesting (All FIDELIS Repositories)

Use the master harvest script to harvest all repositories from the FIDELIS CSV:

```bash
# Activate virtual environment first
source venv/bin/activate

# Dry run - see what would be harvested
python harvest_all.py --dry-run

# Harvest all repositories
python harvest_all.py

# Harvest with a limit (good for testing)
python harvest_all.py --limit 5

# Filter by name/URL
python harvest_all.py --filter pangaea
python harvest_all.py --filter dataverse

# Combine options
python harvest_all.py --filter dans --limit 3
```

Output:
- Individual JSON files saved to `output/` (e.g., `PANGAEA.json`)
- Summary report: `output/_harvest_summary.json`

The script reads from `repo_harvester_server/SG4 FIDELIS repos.csv` which is the master list of repositories to harvest.

## 🧠 Data Model & Schema

The output of this harvester is typed according to the EDEN Schema.

* Context Definition:  [`schema/context.jsonld`](./schema/context.jsonld)
* Defines the mapping to DCAT, Schema.org, and SKOS.
* Target Example:  [`schema/examples/full_registry_graph.json`](./schema/examples/full_registry_graph.json)
* For Frontend/ElasticSearch Developers:  Use this file to configure your index mappings and UI facets.

## 🗄️ Apache Jena Fuseki (Triple Store)

The harvester can optionally save harvested metadata to an Apache Jena Fuseki triple store. This is useful for querying the data with SPARQL.

### 1. Download and Install Fuseki

Important: Install Fuseki in a separate directory, not inside this repository.

```bash
# Create a directory for Fuseki (outside the repo)
mkdir -p ~/tools && cd ~/tools

# Download Fuseki (check https://jena.apache.org/download/ for latest version)
wget https://dlcdn.apache.org/jena/binaries/apache-jena-fuseki-5.6.0.tar.gz

# Extract
tar -xzf apache-jena-fuseki-5.6.0.tar.gz
cd apache-jena-fuseki-5.6.0
```

### 2. Start Fuseki Server

```bash
# From the Fuseki directory (e.g., ~/tools/apache-jena-fuseki-5.6.0)

# Create data directory for persistent storage
mkdir -p ./data

# Start with an in-memory dataset (data lost on restart)
./fuseki-server --update --mem /service_registry_store

# Or for persistent storage (recommended)
./fuseki-server --update --tdb2 --loc=./data /service_registry_store
```

**Note:** The `--update` flag is required to enable the Graph Store Protocol for writing data.

Fuseki will start on `http://localhost:3030`:
- Admin UI: http://localhost:3030/
- SPARQL Endpoint: http://localhost:3030/service_registry_store/sparql
- Graph Store: http://localhost:3030/service_registry_store/data

### 3. Verify Connection

* The harvester expects Fuseki at `http://localhost:3030/service_registry_store/data`
* This is configured in `repo_harvester_server/config.py`
* Once Fuseki is running, the harvester will autosave triples when harvesting
* Without Fuseki, you'll see connection errors in logs but JSON files will still be saved

### 4. Query the Data

After harvesting, query via SPARQL at: `http://localhost:3030/#/dataset/service_registry_store/query`

Important: The harvester stores data in named graphs (one per source/repository), not the default graph. You must use `GRAPH` in your queries:

```sparql
# List all harvested repositories
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?graph ?repo ?title WHERE {
  GRAPH ?graph {
    ?repo a dcat:Catalog ;
          dct:title ?title .
  }
}
```

```sparql
# List all named graphs
SELECT DISTINCT ?g WHERE {
  GRAPH ?g { ?s ?p ?o }
}
```

```sparql
# Find all services across all repositories
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX dct: <http://purl.org/dc/terms/>

SELECT ?repoTitle ?serviceTitle ?endpoint WHERE {
  GRAPH ?g {
    ?repo a dcat:Catalog ;
          dct:title ?repoTitle .
    ?repo dcat:service ?service .
    ?service dct:title ?serviceTitle ;
             dcat:endpointURL ?endpoint .
  }
}
```

Named graphs follow the pattern: `eden://harvester/{source}/{repository_url}`
(e.g., `eden://harvester/re3data/https://pangaea.de/`)

## 🛠 Development

 Key Dependencies:
* `connexion[flask]`: Handles the API server and Swagger validation
* `rdflib`: Parses RDF/JSON-LD data
* `lxml`: Parses HTML meta tags
* `requests`: Fetches web pages

## Troubleshooting

* To change how fields are mapped (e.g., mapping `dct:title` instead of `sdo:name`), edit:
`repo_harvester_server/helper/MetadataHelper.py`
