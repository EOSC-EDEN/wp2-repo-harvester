# EDEN WP2 Repository Harvester

Collects, aggregates, and normalizes metadata from scientific repositories (re3data, FAIRsharing, embedded JSON-LD, Signposting). Outputs standardized DCAT JSON-LD for the EDEN-FIDELIS registry.

## Quick Start

```bash
python3 -m venv venv && source venv/bin/activate
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

Then visit http://localhost:8080/ui or:

```bash
curl "http://localhost:8080/?url=https://pangaea.de"
```

## Documentation

- [Quickstart Guide](docs/quickstart.md) — Setup, installation, harvesting
- [Technologies](docs/technologies.md) — Stack, dependencies, data models
- [FAIRsharing](docs/fairsharing.md) — FAIRsharing API integration and authentication
- [Fuseki Setup](docs/fuseki.md) — Optional triple store for SPARQL queries

## Key Files

| Path                                          | Description                                  |
| --------------------------------------------- | -------------------------------------------- |
| `schema/context.jsonld`                       | JSON-LD context (DCAT, Dublin Core mappings) |
| `schema/examples/full_registry_graph.json`    | Example output for frontend/ElasticSearch    |
| `repo_harvester_server/helper/`               | Core harvesting logic                        |
| `repo_harvester_server/SG4 FIDELIS repos.csv` | Master repository list                       |
