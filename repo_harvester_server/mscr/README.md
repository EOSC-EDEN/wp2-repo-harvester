# MSCR Integration Module

This module handles the integration with the FAIRCORE4EOSC Metadata Schema & Crosswalk Registry (MSCR).

It is designed to offload the "translation" of metadata (e.g., from re3data XML or Schema.org JSON-LD to EDEN JSON-LD) to the external MSCR service, rather than hardcoded parsers in Python.

## Structure

* `harvester.py`: main entry point, fetches data, orchestrates transformation
* `client.py`: handles raw HTTP requests to the MSCR API
* `config.py`: configuration for API URLs and Schema IDs

## Secrets

### Registration

* Register at: https://mscr-release.2.rahtiapp.fi/en/
* Login with e.g. GitHub

### Retrieving API token

* After registration, login to https//mscr-release.2.rahtiapp.fi/groups
* From there, in the user detail tab, there is a button for creating API token.
* You can check this documentation for creating API token and using API here https://cscfi.github.io/mscr-docs/mscr/api-getting-started/
* You should find most of the MSCR API details here https://mscr-release.2.rahtiapp.fi/datamodel-api/swagger-ui/index.html
