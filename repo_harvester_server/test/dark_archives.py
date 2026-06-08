import json
from repo_harvester_server.helper.DarkArchiveHarvester import DarkArchiveHarvester

# Auto-discover all dark archives from re3data (databaseAccess=closed filter)
# To harvest specific IDs instead, pass a list: h.harvest(['r3d100013353', ...])

h = DarkArchiveHarvester()
records = h.harvest()

print("\n--- DARK ARCHIVE RECORDS ---")
print(json.dumps(records, indent=4))
