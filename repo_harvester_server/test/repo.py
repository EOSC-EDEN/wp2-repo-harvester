import json
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


#repouri = 'https://dummyrepository.org/'

#repouri = 'https://www.pangaea.de/'
#repouri = 'https://data.4tu.nl/'


#repouri = 'https://data.sciencespo.fr/dataverse/cdsp'
#repouri = 'https://borealisdata.ca/'
repouri = 'https://about.coscine.de/' #has FAIRsharing entry, re3data initially fails
#repouri =  'https://www.wdc-climate.de/ui/' # has re3data entry, FAIRsharing initially fails



harvester = RepositoryHarvester(repouri)

final_records = harvester.harvest()

print("\n--- FINAL EXPORTED RECORDS ---")
print(json.dumps(final_records, indent=4))
