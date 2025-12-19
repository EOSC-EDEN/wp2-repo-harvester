import logging
import json
import requests
from repo_harvester_server.mscr.client import MSCRClient

# Configure logging
logging.basicConfig(level=logging.INFO)

def main():
    print("--- MSCR Comprehensive Search ---")
    
    # Initialize
    try:
        client = MSCRClient()
    except Exception as e:
        print(f"❌ Error initializing client: {e}")
        return

    # 1. Fetch ALL items (Search API)
    # We set limit=200 to cover the 104 items reported
    endpoint = f"{client.api_url}/frontend/mscrSearch"
    params = {
        'limit': 200, 
        'type': 'CROSSWALK' # Filter strictly for Crosswalks (excludes Schemas)
    }
    
    print(f"🔍 Searching {endpoint} for Crosswalks...")
    
    try:
        response = requests.get(endpoint, headers=client.headers, params=params, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ API Error {response.status_code}: {response.text}")
            return

        data = response.json()
        
        # Extract the list of hits from ElasticSearch response structure
        # Structure is usually: hits -> hits -> [ {_source: ...}, ... ]
        raw_hits = data.get('hits', {}).get('hits', [])
        
        print(f"✅ Retrieved {len(raw_hits)} crosswalks.")
        print("-" * 60)
        print(f"{'PID':<45} | {'Name/Label':<30}")
        print("-" * 60)

        found_re3data = False
        found_schema = False

        for hit in raw_hits:
            source = hit.get('_source', {})
            
            # Extract useful fields
            pid = source.get('pid') or source.get('id') or "N/A"
            # Label might be a dict {"en": "..."} or a string
            label_obj = source.get('label', {})
            if isinstance(label_obj, dict):
                label = label_obj.get('en') or list(label_obj.values())[0] or "Unnamed"
            else:
                label = str(label_obj)
            
            description = str(source.get('description', '')).lower()
            full_text = (label + " " + description).lower()

            # --- MATCHING LOGIC ---
            is_match = False
            
            # Check for Re3Data
            if "re3" in full_text or "data" in full_text and "repo" in full_text:
                print(f"🌟 POTENTIAL RE3DATA:  {pid:<45} | {label}")
                found_re3data = True
                is_match = True

            # Check for EDEN / Schema.org
            if "eden" in full_text or "schema" in full_text or "json" in full_text:
                print(f"🌟 POTENTIAL SCHEMA:   {pid:<45} | {label}")
                found_schema = True
                is_match = True
            
            # Print everything else just in case (optional, maybe too noisy)
            # else:
            #     print(f"  {pid:<45} | {label}")

        print("-" * 60)
        
        if not found_re3data:
            print("⚠️ Could not definitively find a 're3data' crosswalk.")
        if not found_schema:
            print("⚠️ Could not definitively find a 'schema.org' crosswalk.")

    except Exception as e:
        print(f"❌ Script failed: {e}")

if __name__ == "__main__":
    main()