import logging
import json
import requests
from repo_harvester_server.mscr.client import MSCRClient

logging.basicConfig(level=logging.INFO)

def main():
    print("--- MSCR Schema Inspector ---")
    client = MSCRClient()

    # 1. Use a known valid Schema ID found in your previous log
    # (This is the source schema for 'anaMapping_V3')
    target_pid = "mscr:schema:89d6477d-4773-462e-a5cb-f2b62a92ca1b"
    
    # Try the frontend endpoint as it returns the full editing model
    url = f"{client.api_url}/frontend/schema/{target_pid}"
    
    print(f"🔍 Fetching Schema details: {target_pid}...")
    
    try:
        resp = requests.get(url, headers=client.headers, timeout=10)
        
        if resp.status_code != 200:
            print(f"❌ Fetch failed: {resp.status_code} {resp.text}")
            return

        data = resp.json()
        
        print("\n✅ VALID SCHEMA STRUCTURE:")
        print("-" * 50)
        print(json.dumps(data, indent=2))
        print("-" * 50)
        
        # Check specific fields we are struggling with
        print("💡 CRITICAL FIELDS FOR CREATION:")
        keys_to_check = ['type', 'subType', 'format', 'state', 'visibility', 'namespace', 'versionLabel', 'languages']
        for k in keys_to_check:
            print(f"   {k}: {data.get(k)}")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()