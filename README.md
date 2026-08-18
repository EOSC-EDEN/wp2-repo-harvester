# EDEN WP2 Repository Harvester

Collects, aggregates, and normalizes metadata from scientific repositories (re3data, FAIRsharing, embedded JSON-LD, Signposting). Outputs standardized DCAT JSON-LD for the EDEN-FIDELIS registry.

## Quick Start

### Docker

```bash
docker build -t eden-harvester .
docker run -p 8080:8080 \
  -e FUSEKI_PATH=http://localhost:3030/service_registry_store/data \
  -e FUSEKI_USERNAME=admin \
  -e FUSEKI_PASSWORD=admin \
  eden-harvester
```

### Local

```bash
python3 -m venv venv && source venv/bin/activate
pip install .
python main.py
```

### Environment variables

| Variable | Description | Default |
| --- | --- | --- |
| `FUSEKI_PATH` | Fuseki Graph Store endpoint | `http://localhost:3030/service_registry_store/data` |
| `FUSEKI_USERNAME` | Fuseki basic auth username | — |
| `FUSEKI_PASSWORD` | Fuseki basic auth password | — |
| `FAIRSHARING_USERNAME` | FAIRsharing API username | — |
| `FAIRSHARING_PASSWORD` | FAIRsharing API password | — |
| `EDEN_ENABLED_REGISTRIES` | Comma-separated registries to consult (`re3data`, `fairsharing`) | `re3data,fairsharing` |
| `EDEN_ALLOW_PRIVATE_TARGETS` | Disables the SSRF address check so private/internal targets can be harvested — **must remain unset on a public host**; it lets a submitted URL reach private/internal addresses | unset (checked) |

Then visit http://localhost:8080/ (the HTML demo page) or the Swagger UI at http://localhost:8080/api/ui/, or fetch JSON directly:

```bash
curl "http://localhost:8080/api/?url=https://pangaea.de"
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
