# Quickstart

## Prerequisites

- Python 3.9+
- Network access to external APIs (re3data.org, FAIRsharing.org)

## Installation

```bash
git clone <repository-url>
cd wp2-repo-harvester

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run the Server

```bash
python main.py
```

- API: http://localhost:8080
- Swagger UI: http://localhost:8080/ui

## Harvest a Repository

```bash
curl "http://localhost:8080/?url=https://pangaea.de"
```

Returns JSON with repository metadata, publisher info, and discovered services.

## Batch Harvesting

Harvest all repositories from the FIDELIS CSV:

```bash
# Preview what would be harvested
python harvest_all.py --dry-run

# Harvest all
python harvest_all.py

# Limit for testing
python harvest_all.py --limit 5

# Filter by name/URL
python harvest_all.py --filter pangaea
python harvest_all.py --filter dataverse

# Combine
python harvest_all.py --filter dans --limit 3
```

**Output:**
- Individual JSON files: `output/<RepoName>.json`
- Summary: `output/_harvest_summary.json`

## Configuration

| File                                                 | Purpose                      |
| ---------------------------------------------------- | ---------------------------- |
| `repo_harvester_server/config.py`                    | Fuseki endpoint URL          |
| `repo_harvester_server/SG4 FIDELIS repos.csv`        | Repositories to harvest      |
| `repo_harvester_server/services_default_queries.csv` | Service protocol definitions |

## Troubleshooting

**Field mapping issues:** Edit `repo_harvester_server/helper/MetadataHelper.py`

**Fuseki connection errors:** The harvester works without Fuseki — JSON files are still saved. See [Fuseki Setup](fuseki.md) if you need SPARQL.

## Next Steps

- [Technologies](technologies.md) — Understand the stack and data models
- [Fuseki Setup](fuseki.md) — Enable SPARQL queries over harvested data
