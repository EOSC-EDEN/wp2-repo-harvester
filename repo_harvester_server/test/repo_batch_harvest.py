import json
import csv
import os
import sys
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester

# Configuration
CSV_FILE = os.path.join(os.path.dirname(__file__), '..', 'FIDELIS repos.csv')
OUTPUT_DIR = "output"

def main():
    # Create output directory if it doesn't exist
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    print(f"🌾 Starting Batch Harvest from: {CSV_FILE}")
    print("--------------------------------")

    try:
        with open(CSV_FILE, mode='r', encoding='utf-8-sig') as infile: # utf-8-sig handles BOM
            reader = csv.DictReader(infile)
            
            for row in reader:
                name = row.get('name', '').strip()
                url = row.get('URL_to_harvest', '').strip()

                if not url:
                    continue

                print(f"\nProcessing: {name} ({url})")
                
                try:
                    # Instantiate and run the harvester
                    # This automatically uses the new cross-registry logic in RepositoryHarvester
                    harvester = RepositoryHarvester(url)
                    
                    # harvest() calls export(save=True) internally, so this saves to Fuseki if configured
                    final_records = harvester.harvest()
                    
                    # Create a safe filename
                    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip().replace(' ', '_')
                    if not safe_name:
                        safe_name = "unnamed_repo"
                    
                    filename = f"{safe_name}.json"
                    filepath = os.path.join(OUTPUT_DIR, filename)

                    # Save the JSON result locally as well
                    with open(filepath, 'w', encoding='utf-8') as outfile:
                        json.dump(final_records, outfile, indent=4)
                    
                    print(f"✅ Saved to {filepath}")

                except Exception as e:
                    print(f"❌ Failed to harvest {url}: {e}")
                    # Optional: print full traceback for debugging
                    # import traceback
                    # traceback.print_exc()

    except FileNotFoundError:
        print(f"❌ Error: CSV file not found at {CSV_FILE}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
        sys.exit(1)

    print("\n--------------------------------")
    print(f"🎉 Harvest complete. Check the '{OUTPUT_DIR}' folder.")

if __name__ == "__main__":
    main()
