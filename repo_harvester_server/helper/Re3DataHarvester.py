import requests
from urllib.parse import urlparse
from lxml import etree
import os
import csv
from .Validator import EndpointValidator

class Re3DataHarvester:
    """
    A harvester for fetching metadata from the re3data.org registry.
    """
    def __init__(self):
        self.api_url = "https://www.re3data.org/api/beta"
        self.ns = {"r3d": "http://www.re3data.org/schema/2-2"}
        self.service_mappings = self._load_service_mappings()
        self.validator = EndpointValidator()

    def _load_service_mappings(self):
        """Loads the service mappings from the CSV file."""
        mappings = {}
        csv_path = os.path.join(os.path.dirname(__file__), '..', 'services_default_queries.csv')
        try:
            with open(csv_path, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                for row in reader:
                    if row['Acronym']:
                        mappings[row['Acronym']] = row['URI']
        except FileNotFoundError:
            print(f"Warning: Service mapping file not found at {csv_path}")
        return mappings

    def harvest(self, catalog_url):
        """
        Public method to harvest metadata for a given URL.
        It searches by the domain and then verifies the results.
        """
        print("Harvesting from re3data...")
        hostname = urlparse(catalog_url).hostname
        if not hostname:
            return None

        try:
            search_url = f"{self.api_url}/repositories?query={hostname}"
            resp = requests.get(search_url, timeout=15)
            resp.raise_for_status()

            root = etree.fromstring(resp.content)
            
            for repo_id_element in root.findall('.//id'):
                repo_id = repo_id_element.text
                
                repo_url = f"{self.api_url}/repository/{repo_id}"
                repo_resp = requests.get(repo_url, timeout=15)
                if repo_resp.status_code != 200:
                    continue

                repo_root = etree.fromstring(repo_resp.content)
                repo_main_url_element = repo_root.find('.//r3d:repositoryURL', self.ns)
                
                if repo_main_url_element is not None and repo_main_url_element.text:
                    re3data_hostname = urlparse(repo_main_url_element.text).hostname
                    if re3data_hostname and re3data_hostname.lower() == hostname.lower():
                        print(f"Found verified re3data entry: {repo_url}")
                        return self._parse_record(repo_root)

        except requests.exceptions.RequestException as e:
            print(f"Re3data API request error: {e}")
        except etree.XMLSyntaxError as e:
            print(f"Error parsing re3data XML: {e}")
            
        return None

    def _parse_record(self, repo_root):
        """
        Parses the detailed XML for a specific repository from re3data.
        """
        def find_text(element, path):
            node = element.find(path, self.ns)
            return node.text.strip() if node is not None and node.text else None

        def find_all_text(element, path):
            return [node.text.strip() for node in element.findall(path, self.ns) if node.text]

        publishers = []
        for inst_element in repo_root.findall(".//r3d:institution", self.ns):
            inst_name = find_text(inst_element, 'r3d:institutionName')
            if inst_name:
                publishers.append({"type": "org:Organization", "name": inst_name})

        services = []
        for api_elem in repo_root.findall(".//r3d:api", self.ns):
            api_type = api_elem.get('apiType')
            api_url = api_elem.text.strip() if api_elem.text else None
            if api_url:
                validation_result = self.validator.validate_url(api_url, api_type)
                services.append({
                    'endpoint_uri': api_url,
                    'type': f"re3data:API:{api_type}" if api_type else "re3data:API",
                    'conforms_to': self.service_mappings.get(api_type),
                    'title': f"{api_type} API" if api_type else "API Service",
                    'validation_status': validation_result
                })

        for syndication_elem in repo_root.findall(".//r3d:syndication", self.ns):
            syndication_type = syndication_elem.get('syndicationType')
            syndication_url = syndication_elem.text.strip() if syndication_elem.text else None
            if syndication_url:
                validation_result = self.validator.validate_url(syndication_url, syndication_type)
                services.append({
                    'endpoint_uri': syndication_url,
                    'type': f"re3data:Syndication:{syndication_type}" if syndication_type else "re3data:Syndication",
                    'conforms_to': self.service_mappings.get(syndication_type),
                    'title': f"{syndication_type} Feed" if syndication_type else "Syndication Feed",
                    'validation_status': validation_result
                })
        
        identifiers = [
            find_text(repo_root, ".//r3d:re3data.orgIdentifier"),
            find_text(repo_root, ".//r3d:repositoryURL")
        ] + find_all_text(repo_root, ".//r3d:repositoryIdentifier")

        metadata = {
            'title': find_text(repo_root, ".//r3d:repositoryName"),
            'description': find_text(repo_root, ".//r3d:description"),
            'identifier': [i for i in identifiers if i],
            'publisher': publishers if publishers else None,
            'contact': find_all_text(repo_root, ".//r3d:repositoryContact"),
            'services': services if services else None,
            'keywords': find_all_text(repo_root, ".//r3d:keyword"),
            'subject': find_all_text(repo_root, ".//r3d:subject")
        }

        return {k: v for k, v in metadata.items() if v}
