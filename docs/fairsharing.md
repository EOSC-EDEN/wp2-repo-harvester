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

* At this stage, you should be able to harvest FAIRsharing metadata with `python harvest_all.py`

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
