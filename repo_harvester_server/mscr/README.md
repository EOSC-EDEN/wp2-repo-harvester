# MSCR Integration Module

This module handles the integration with the FAIRCORE4EOSC Metadata Schema & Crosswalk Registry (MSCR).

It is designed to offload the "translation" of metadata (e.g., from re3data XML or Schema.org JSON-LD to EDEN JSON-LD) to the external MSCR service, rather than hardcoded parsers in Python.

## Structure

* `harvester.py`: main entry point, fetches data, orchestrates transformation
* `client.py`: handles raw HTTP requests to the MSCR API
* `config.py`: configuration for API URLs and Schema IDs
