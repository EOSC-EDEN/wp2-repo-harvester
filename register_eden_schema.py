import logging
import json
import requests
from pathlib import Path
from repo_harvester_server.mscr.client import MSCRClient

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    print("--- MSCR Robust Schema Registration ---")
    
    try:
        client = MSCRClient()
        if not client.check_connection():
            print("❌ Authentication failed. Check credentials.")
            return
    except Exception as e:
        print(f"❌ Client Error: {e}")
        return

    # Define Schemas
    schemas_to_register = [
        {
            "label": "EDEN Repository Schema",
            "description": "JSON-LD Schema for EDEN Repository Registry",
            "file_path": "schema/repo_schema.json",
            "namespace": "https://eden-fidelis.eu/schemas/repo",
            "version": "1.0",
            # CHANGED: 'JSON' -> 'JSONSCHEMA' based on API error message
            "format": "JSONSCHEMA" 
        },
        {
            "label": "EDEN JSON-LD Context",
            "description": "Context definition for EDEN",
            "file_path": "schema/context.jsonld",
            "namespace": "https://eden-fidelis.eu/context",
            "version": "1.0",
            # CHANGED: 'JSON' -> 'JSONSCHEMA' 
            "format": "JSONSCHEMA"
        }
    ]

    for item in schemas_to_register:
        path = Path(item["file_path"])
        if not path.exists():
            print(f"⚠️  Skipping {item['label']}: File {path} not found.")
            continue

        print(f"\n📤 Registering: {item['label']}...")
        
        # 1. Prepare Metadata Object
        metadata_dict = {
            "label": {"en": item["label"]},
            "description": {"en": item["description"]},
            "type": "SCHEMA",
            "subType": "DATA_SCHEMA",
            "state": "DRAFT",
            "visibility": "PUBLIC",
            "versionLabel": item["version"],
            "namespace": item["namespace"],
            "format": item["format"],
            "languages": ["en"]
        }
        
        # 2. Prepare Multipart Payload
        metadata_json_str = json.dumps(metadata_dict)
        
        with open(path, 'r') as f:
            file_content = f.read()

        files = {
            'metadata': (None, metadata_json_str, 'application/json'),
            'file': (path.name, file_content, 'application/json')
        }
        
        # 3. Send Request
        url = f"{client.api_url}/frontend/schemaFull"
        headers = {k:v for k,v in client.headers.items() if k.lower() != 'content-type'}
        
        try:
            resp = requests.put(url, headers=headers, files=files, timeout=60)
            
            if resp.status_code in [200, 201]:
                result = resp.json()
                pid = result.get('pid') or result.get('id')
                print(f"   ✅ Success! PID: {pid}")
            else:
                print(f"   ❌ Failed: {resp.status_code}")
                # Print less verbose error if it's huge, but enough to debug
                print(f"   Response: {resp.text[:500]}")
                
        except Exception as e:
            print(f"   ❌ Network Error: {e}")

if __name__ == "__main__":
    main()