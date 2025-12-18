import logging
import sys

# Update the import to point to the internal package
# WAS: from mscr.client import MSCRClient
from repo_harvester_server.mscr.client import MSCRClient

# Configure logging to see output clearly
logging.basicConfig(level=logging.INFO)

def main():
    print("--- MSCR Crosswalk Discovery ---")
    try:
        client = MSCRClient()
    except Exception as e:
        print(f"❌ Error initializing client: {e}")
        return
    
    # 1. Check Auth
    if client.check_connection():
        print("✅ Authentication successful.")
    else:
        print("❌ Authentication failed. Check repo_harvester_server/mscr/mscr_credentials.json.")
        return

    # 2. List Crosswalks
    print("\nfetching available crosswalks...")
    crosswalks = client.get_all_crosswalks()
    
    found = False
    for cw in crosswalks:
        # Depending on API structure, adjust fields. Usually has 'name', 'pid' or 'id'
        cw_name = cw.get('label') or cw.get('name') or "Unknown Name"
        cw_id = cw.get('pid') or cw.get('id')
        cw_desc = cw.get('description', '')
        
        print(f"ID: {cw_id} | Name: {cw_name}")
        
        # Heuristic to find relevant ones
        if "re3data" in cw_name.lower() or "re3data" in cw_desc.lower():
            print(f"   >>> POTENTIAL MATCH FOR re3data: {cw_id}")
            found = True
        if "schema" in cw_name.lower() or "json" in cw_name.lower():
            print(f"   >>> POTENTIAL MATCH FOR Schema.org: {cw_id}")
            found = True

    if not found:
        print("\n⚠️ No obvious crosswalks found. You may need to create one via the MSCR UI.")

if __name__ == "__main__":
    main()