import json
from pathlib import Path
from urllib.parse import urlparse

from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


#repouri = 'https://dummyrepository.org/'

#repouri = 'https://www.pangaea.de/'
#repouri = 'https://data.4tu.nl/'


#repouri = 'https://data.sciencespo.fr/dataverse/cdsp'


repouri = 'https://www.polarmeteoroloji.com/'
#repouri = 'https://about.coscine.de/' #has FAIRsharing entry, re3data initially fails
#repouri =  'https://www.wdc-climate.de/ui/' # has re3data entry, FAIRsharing initially fails

#repouri = 'https://naehrwertdaten.ch/de/'

harvester = RepositoryHarvester(repouri)

final_records = harvester.harvest()

print("\n--- FINAL EXPORTED RECORDS ---")
print(json.dumps(final_records, indent=4))

# uncomment to keep a local copy. The file is
# named after the repository, so testing another one does not overwrite it.
"""
parts = urlparse(repouri)
outfile = Path(__file__).resolve().parents[2] / 'output' / (
    (parts.netloc + parts.path).strip('/').replace('/', '_') + '.json'
)
outfile.parent.mkdir(exist_ok=True)
outfile.write_text(json.dumps(final_records, indent=4), encoding='utf-8')
print(f"\nSaved to {outfile}")
"""