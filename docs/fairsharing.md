# FAIRsharing Integration

* The harvester integrates with https://fairsharing.org to fetch metadata about data repositories, standards, and policies.

## Authentication

* First, go to https://fairsharing.org and create an account
* Your FAIRsharing account must be linked to an organisation to access the API
* Visit https://fairsharing.org/profiles/edit to associate your account with your institution.
* Then, to access the FAIRsharing API, define environment variables:

```bash
export FAIRSHARING_USERNAME="your_username"
export FAIRSHARING_PASSWORD="your_password"
```

* At this stage, you should be able to harvest FairSharing metadata with `python harvest_all.py` 

## Harvesting Strategies

### By URL (Automatic)

When harvesting a repository URL, the harvester attempts to find a matching FAIRsharing record:

1. Hostname search - Queries FAIRsharing using the repository's hostname
2. Name search - Falls back to searching by the first part of the hostname (e.g., `zenodo` from `zenodo.org`)

The harvester matches records by comparing homepage URLs with subdomain tolerance (e.g., `about.coscine.de` matches `coscine.de`).

### By DOI (Direct)

When a FAIRsharing DOI is known, use `harvest_by_id()` for exact matching:

```bash
harvester = FAIRsharingHarvester()
metadata = harvester.harvest_by_id("10.25504/FAIRsharing.zcveaz")
```

## Output Example

A successful FAIRsharing harvest returns normalized metadata:

```json
{
  "title": "4TU.ResearchData",
  "identifier": ["10.25504/FAIRsharing.zcveaz"],
  "resource_type": "repository",
  "publisher": [{"name": "4TU.ResearchData"}],
  "description": "4TU.ResearchData is an international data repository...",
  "access_terms": "open",
  "contact": [{"mail": "researchdata@4tu.nl"}],
  "subject": ["Engineering", "Natural Sciences"],
  "license": ["https://creativecommons.org/licenses/by/4.0/"],
  "policies": [
    {
      "type": "premis:PreservationPolicy",
      "policy_uri": "https://...",
      "title": "Data Preservation Policy"
    }
  ]
}
```
