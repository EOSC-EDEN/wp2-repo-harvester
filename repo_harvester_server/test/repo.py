import json
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


#repouri = 'https://dummyrepository.org/'

#repouri = 'https://www.pangaea.de/'
repouri = 'https://data.4tu.nl/'



harvester = RepositoryHarvester(repouri)

final_records = harvester.harvest()

print("\n--- FINAL EXPORTED RECORDS ---")
print(json.dumps(final_records, indent=4))
