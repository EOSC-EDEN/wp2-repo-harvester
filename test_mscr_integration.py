#!/usr/bin/env python3
import json
import logging

# Import from the new module
from repo_harvester_server.mscr import MSCRHarvester

# Setup logging
logging.basicConfig(level=logging.INFO)

def test_integration():
    print("------------------------------------------------")
    print("Testing MSCR Integration (Isolated Module)")
    print("------------------------------------------------")

    # 1. Test URL (e.g., an re3data entry)
    test_url = "https://www.re3data.org/api/v1/repository/r3d100013166" # Pangaea re3data XML
    
    # 2. Instantiate the new harvester
    harvester = MSCRHarvester(test_url)
    
    # 3. Run harvest
    harvester.harvest()
    
    # 4. Inspect results
    print("\n--- Resulting Metadata (EDEN Format) ---")
    print(json.dumps(harvester.metadata, indent=2))

    if harvester.metadata.get('title') == "MOCKED DATA FROM MSCR":
         print("\nNOTE: This is mock data. To run real extraction:")
         print("1. Set MOCK_MODE = False in repo_harvester_server/mscr/config.py")
         print("2. Ensure MSCR_API_URL is correct.")

if __name__ == "__main__":
    test_integration()