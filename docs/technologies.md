# EDEN WP2 Repository Harvester - Technology Stack

## Overview

The EDEN WP2 Repository Harvester is a web service that collects, aggregates, and normalizes metadata from scientific data repositories. It orchestrates harvesting from multiple sources including self-hosted metadata (JSON-LD, meta tags, signposting links) and external registries (re3data.org, FAIRsharing.org). The harvested metadata is transformed into the standardized EDEN-FIDELIS JSON-LD schema.

---

## Programming Languages

| Language     | Usage                                          |
| ------------ | ---------------------------------------------- |
| Python 3     | Primary language                               |
| YAML         | API specification (OpenAPI/Swagger)            |
| JSON/JSON-LD | Data models, schemas, context definitions      |
| XSLT         | HTML/RDF transformation (2 stylesheets)        |
| CSV          | Repository lists and service protocol mappings |

---

## Server & Runtime

### API Server
- Framework: Connexion (Flask-based RESTful API framework)
- ASGI Server: Uvicorn
- Port: 8080 (development)
- Entry Point: `main.py`
- Swagger UI: `http://localhost:8080/ui`

### Triple Store (Optional)
- Database: Apache Jena Fuseki 5.6.0
- Port: 3030
- Storage: TDB2 with named graphs per repository
- Protocol: Graph Store Protocol for SPARQL/RDF persistence

### Runtime Requirements
- Python 3.9+
- Virtual environment (venv)
- Network access to external APIs

---

## Libraries & Dependencies

### Core Dependencies

| Library                             | Version  | Purpose                                     |
| ----------------------------------- | -------- | ------------------------------------------- |
| connexion[uvicorn,flask,swagger-ui] | -        | RESTful API framework with OpenAPI support  |
| rdflib                              | 7.5.0    | RDF/OWL parsing and JSON-LD manipulation    |
| lxml                                | 6.0.2    | XML/HTML parsing and XSLT transformations   |
| requests                            | >=2.30.0 | HTTP client for fetching web resources      |
| jmespath                            | -        | JSON query language for metadata extraction |
| python-dateutil                     | -        | Date/time parsing utilities                 |
| six                                 | -        | Python 2/3 compatibility                    |

### Standard Library Modules
- `logging`, `json`, `datetime`, `csv`, `argparse`, `urllib`, `pathlib`, `uuid`, `copy`

---

## Data Models

### Core Model: RepositoryInfo

```python
class RepositoryInfo:
    repoURI: str        # Repository URL identifier
    re3dataID: str      # Optional registry ID
    metadata: Dict      # DCAT JSON-LD record
    services: Dict      # Service endpoint descriptions
    policies: Dict      # Data policies
```

### Output Schema: DCAT CatalogRecord

The harvested data conforms to the DCAT (Data Catalog Vocabulary) standard:

```
CatalogRecord
├── prov:wasGeneratedBy      # Harvesting activity metadata
│   ├── source               # Origin (self-hosted, re3data, fairsharing)
│   ├── timestamp            # Harvest datetime
│   └── method               # Extraction method used
│
└── prov:hadPrimarySource    # The harvested Catalog
    ├── dct:title            # Repository name
    ├── dct:identifier       # Unique identifier
    ├── dct:description      # Repository description
    ├── dct:publisher        # foaf:Agent (name, country)
    ├── dct:contactPoint     # vCard contact information
    ├── dcat:service[]       # Array of DataService endpoints
    ├── dcat:keyword         # Subjects/themes
    ├── dct:language         # Content language
    └── dct:license          # License information
```

### DataService Model

Each discovered service endpoint contains:

```
dcat:DataService
├── dcat:endpointURL         # Service URL
├── dct:title                # Service name
├── dct:conformsTo           # Protocol/standard URI
├── dcat:mediaType           # Output format
└── dcat:servesDataset       # Linked datasets
```

### JSON-LD Context

The `schema/context.jsonld` file maps semantic namespaces:
- dcat: Data Catalog Vocabulary
- dct: Dublin Core Terms
- foaf: Friend of a Friend
- vcard: vCard Ontology
- prov: Provenance Ontology
- obo: Open Biological Ontologies
- Custom EDEN namespaces

### Validation Schema

`schema/repo_schema.json` defines JSON Schema (draft 2020-12) validation:
- Required fields: `title`
- Optional: `services`, `publisher`, `contact`, `license`, `keywords`

---

## Metadata Extraction (JMESPATH Queries)

The system uses JMESPATH queries for normalizing heterogeneous metadata sources:

| Query                | Purpose                                                        |
| -------------------- | -------------------------------------------------------------- |
| `REPO_INFO_QUERY`    | Extracts basic repository info (title, publisher, description) |
| `SERVICE_INFO_QUERY` | Extracts service endpoints (URI, type, format)                 |
| `POLICY_INFO_QUERY`  | Extracts policy information                                    |
| `FAIRSHARING_QUERY`  | Specialized parser for FAIRsharing API responses               |
| `DCAT_EXPORT_QUERY`  | Master query for complete DCAT output                          |

---

## Service Protocol Definitions

The system recognizes 50+ service protocols defined in `services_default_queries.csv`:

| Category         | Protocols                                               |
| ---------------- | ------------------------------------------------------- |
| Data Access      | OAI-PMH, REST, SPARQL, OpenAPI, SWORD                   |
| Web Services     | THREDDS, ERDDAP, OpenDAP                                |
| Discovery        | Sitemaps, OpenSearch, Atom/RSS                          |
| Interoperability | IIIF, FAIRiCAT, Linked Data Notifications               |
| Geo/Science      | OGC (WMS, WFS, WCS, CSW), IVOA (SCS, SIA), TAPIR, DiGIR |

---

## Project Structure

```
wp2-repo-harvester/
├── main.py                              # API server entry point
├── harvest_all.py                       # Batch harvesting script
├── requirements.txt                     # Python dependencies
├── README.md                            # Project documentation
│
├── repo_harvester_server/
│   ├── config.py                        # Fuseki endpoint configuration
│   ├── controllers/
│   │   └── get_repo_info_controller.py  # Main API handler
│   ├── models/
│   │   └── repository_info.py           # Data model classes
│   ├── helper/
│   │   ├── RepositoryHarvester.py       # Main orchestrator
│   │   ├── MetadataHelper.py            # Self-hosted extraction
│   │   ├── Re3DataHarvester.py          # re3data.org integration
│   │   ├── FAIRsharingHarvester.py      # FAIRsharing.org client
│   │   ├── SignPostingHelper.py         # Signposting/Linkset parsing
│   │   ├── GraphHelper.py               # JSON-LD normalization
│   │   └── JMESPATHQueries.py           # Metadata queries
│   ├── data/
│   │   └── country_codes.py             # ISO 3166 mapping
│   ├── swagger/
│   │   └── swagger.yaml                 # OpenAPI 3.0.4 spec
│   ├── xslt/
│   │   ├── metatag2json.xslt            # Meta tags to JSON
│   │   └── rdf2json.xslt                # RDF to JSON
│   ├── SG4 FIDELIS repos.csv            # Repository list (40+)
│   └── services_default_queries.csv     # Protocol definitions
│
├── schema/
│   ├── context.jsonld                   # JSON-LD context
│   ├── repo_schema.json                 # Validation schema
│   └── examples/
│       └── full_registry_graph.json     # Example output
│
└── output/                              # Harvested results
```

---

## Architectural Components

### RepositoryHarvester (Orchestrator)
Main entry point managing the cascading fallback strategy:
1. Self-hosted metadata extraction
2. Registry-based harvesting (re3data, FAIRsharing)
3. Metadata merging and DCAT export
4. Optional Fuseki persistence

### MetadataHelper (Self-Hosted Extractor)
- Parses embedded JSON-LD
- Extracts HTML meta tags via XSLT
- Processes signposting links (RFC 8288)
- Fuzzy RDF property matching

### JSONGraph (Graph Normalizer)
- Detects main entity in JSON-LD graphs
- Strips namespace prefixes for JMESPATH compatibility
- Rebuilds normalized graph structure

### SignPostingHelper (Linkset Parser)
- Parses HTTP Link headers and `<link>` tags
- Resolves linksets (JSON and text formats)
- Extracts `describedby`, `linkset`, and `api-catalog` relations

### Registry Harvesters
- Re3DataHarvester: XML API integration with hostname matching
- FAIRsharingHarvester: JWT-authenticated REST API client

---

## API Endpoint

### Single Repository Harvesting

```
GET http://localhost:8080/?url=<REPOSITORY_URL>
```

### Response Structure

```json
{
  "repoURI": "https://example.org/repository",
  "metadata": { /* DCAT CatalogRecord */ },
  "services": [ /* dcat:DataService array */ ]
}
```

---

## Standards Compliance

- DCAT 3: Data Catalog Vocabulary
- JSON-LD 1.1: Linked Data serialization
- OpenAPI 3.0.4: API specification
- RFC 8288: Web Linking (Signposting)
- PROV-O: Provenance ontology
- Dublin Core Terms: Metadata elements
- vCard: Contact information
- FOAF: Agent descriptions
