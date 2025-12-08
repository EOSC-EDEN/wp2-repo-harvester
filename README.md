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

### 3. Real World Usage (Batch Harvesting)

To harvest a list of repositories, you can loop through them sending requests to your local server.

 Example (Bash): 
```bash
for url in "https://zenodo.org" "https://pangaea.de"; do
    echo "Harvesting $url..."
    curl -s "http://localhost:8080/?url=$url" >> results.json
done
```

## 🧠 Data Model & Schema

The output of this harvester is strictly typed according to the EDEN Schema.

* Context Definition:  [`schema/context.jsonld`](./schema/context.jsonld)
* Defines the mapping to DCAT, Schema.org, and SKOS.
* Target Example:  [`schema/examples/full_registry_graph.json`](./schema/examples/full_registry_graph.json)
* For Frontend/ElasticSearch Developers:  Use this file to configure your index mappings and UI facets.

## 🛠 Development

 Key Dependencies: 
* `connexion[flask]`: Handles the API server and Swagger validation.
* `rdflib`: Parses RDF/JSON-LD data.
* `lxml`: Parses HTML meta tags.
* `requests`: Fetches web pages.
* Change how fields are mapped (e.g., mapping `dct:title` instead of `sdo:name`), edit:
`repo_harvester_server/helper/MetadataHelper.py`
