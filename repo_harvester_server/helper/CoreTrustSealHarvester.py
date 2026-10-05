import json
from datetime import datetime
from urllib.parse import urlparse

import requests
import os
from rapidfuzz import process, fuzz
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

class CoreTrustSealHarvester(object):

    logger = logging.getLogger('CoreTrustSealHarvester')

    def __init__(self):
        self.graphql_endpoint = 'https://backend.amt.coretrustseal.org/graphql'
        cts_json = {}
        self.repodict = {}
        self.repolist = []
        self.cts_data_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'core_trust_seal_data.json')
        try:
            if not os.path.isfile(self.cts_data_path):
                cts_json = self.get_cts_json()
            else:
                with open(self.cts_data_path, mode='r', encoding='utf-8') as infofile:
                    cts_json = json.load(infofile)


            if cts_json.get("data"):
                for cert in cts_json["data"].get('certificates'):
                    cert_req = cert.get("certificationRequest")
                    if cert_req:
                        certificate = cert_req.get("certificate")
                        cert_id = certificate.get("id")

                        repository = cert_req.get("repository")
                        repo_uri = repository.get("website")
                        repo_id = repository.get("id")
                        repoinfo = {
                            "resource_type" : "cts:Repository",
                            "title" : repository.get("name"),
                            "identifier" : [repository.get("pid"), repo_uri],
                            "description" : repository.get("description")
                        }
                        if repository.get("institution"):
                            institution = repository.get("institution")
                            repoinfo["publisher"] = {"type": "org:Organization", "name": institution.get("name")}
                            repoinfo["country"] =institution.get("country")
                            if institution.get("email"):
                                repoinfo["contact"] = {"email": institution.get("email")}

                        status = False
                        if datetime.strptime(cert_req.get("validUntil"), '%Y-%m-%d') >= datetime.now():
                            status = True

                        certinfo = {
                            "url" : cert_req.get("pidUrl"),
                            "active" : status,
                            "expires" : cert_req.get("validUntil"),
                            "issuer" : "CoreTrustSeal"
                        }

                    if not self.repodict.get(repo_uri):
                        self.repodict[repo_uri] = repoinfo
                        self.repodict[repo_uri]['certificates'] =[certinfo]
                    else:
                        self.repodict[repo_uri]['certificates'].append(certinfo)
        except Exception as e:
            self.logger.warning('CoreTrustSeal data initialisation failed: '+ str(e))

    def harvest(self,catalog_url, repository_name = None):
        self.logger.info("-- Harvesting from CoreTrustSeal -- ")
        def clean_url(url):
            # removes http etc
            parsed = urlparse(url.lower().strip())
            netloc = parsed.netloc.replace("www.", "")
            path = parsed.path.rstrip("/")
            return f"{netloc}{path}"

        if self.repodict:
            if catalog_url:
                if self.repodict.get(catalog_url):
                    return self.repodict.get(catalog_url)
                url_choices = {clean_url(u):u for u in self.repodict.keys()}
                best_url_match = process.extractOne(clean_url(str(catalog_url)), url_choices.keys(), scorer=fuzz.WRatio)
                if best_url_match:
                    if best_url_match[1] >= 80:
                        found_url =  url_choices[best_url_match[0]]
                        return self.repodict[found_url]
            if repository_name:
                name_choices = {v.get("title"):u for u,v in self.repodict.items()}
                best_name_match = process.extractOne(str(repository_name), name_choices.keys(), scorer=fuzz.WRatio)
                if best_name_match:
                    if best_name_match[1] >= 80 or repository_name in best_name_match[0]:
                        found_url = name_choices[best_name_match[0]]
                        return self.repodict[found_url]


    def get_cts_json(self):
        data = {}
        self.logger.info('Refreshing CoreTrustSeal data cache')
        graphql_query = {"operationName":"getCertificates","variables":{},"query":"query getCertificates  {certificates {id\ncertificationRequest {certificate {id\ncertificateFileKey} repository {description\nid\nname\npid\nwebsite\ninstitution { address\ncity\ncountry\nemail\nname }}reviewDueDate\nreviewLoopIteration\nstatus\nvalidUntil\nuuid\npidUrl}}}"}
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}

        try:
            response = requests.post(self.graphql_endpoint, json=graphql_query, headers=headers)
            if response.status_code == 200:
                data = json.loads(response.text)
                with open(self.cts_data_path, mode='w', encoding='utf-8') as cts_file:
                    cts_file.write(json.dumps(data))
            else:
                print(response.status_code, response.text)
        except requests.exceptions.RequestException as e:
            self.logger.warning("Retrieving CoreTrustSeal data failed "+str(e))
        return data

cts = CoreTrustSealHarvester()
print(cts.harvest(catalog_url=None, repository_name="PANGAEA"))