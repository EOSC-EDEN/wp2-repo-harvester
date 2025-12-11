import requests
from urllib.parse import urlparse
from lxml import etree

class Re3DataHarvester:
    """
    A harvester for fetching metadata from the re3data.org registry.
    """
    def __init__(self):
        self.api_url = "https://www.re3data.org/api/beta" # Use beta, otherwise query wont work.. v1 for detailed records
        self.ns = {"r3d": "http://www.re3data.org/schema/2-2"}

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
            # Search for the repository by its hostname
            search_url = f"{self.api_url}/repositories?query={hostname}"
            resp = requests.get(search_url, timeout=15)
            resp.raise_for_status()
            print('#### 1', search_url)
            root = etree.fromstring(resp.content)
            
            # Iterate through all repository IDs found in the search result
            for repo_id_element in root.findall('.//id'):
                repo_id = repo_id_element.text
                print('#### 2', repo_id)

                # Fetch the full, detailed record for this specific repository
                repo_url = f"{self.api_url}/repository/{repo_id}"
                repo_resp = requests.get(repo_url, timeout=15)
                if repo_resp.status_code != 200:
                    continue

                # Parse the detailed record and verify the URL
                repo_root = etree.fromstring(repo_resp.content)
                repo_main_url_element = repo_root.find('.//r3d:repositoryURL', self.ns)
                
                if repo_main_url_element is not None and repo_main_url_element.text:
                    re3data_hostname = urlparse(repo_main_url_element.text).hostname
                    # Crucial check: ensure the hostname in the record matches our target
                    if re3data_hostname and re3data_hostname.lower() == hostname.lower():
                        print(f"Found verified re3data entry: {repo_url}")
                        return self._parse_record(repo_root) # Parse and return if verified

        except requests.exceptions.RequestException as e:
            print(f"Re3data API request error: {e}")
        except etree.XMLSyntaxError as e:
            print(f"Error parsing re3data XML: {e}")
            
        return None # Return None if no verified match is found

    def _parse_record(self, repo_root):
        """
        Parses the detailed XML for a specific repository from re3data.
        """
        def find_text(path):
            node = repo_root.find(path, self.ns)
            return node.text.strip() if node is not None and node.text else None

        # Extract publisher as a list of dictionaries
        publishers = []
        inst_name = find_text(".//r3d:institutionName")
        if inst_name:
            publishers.append({"type": "org:Organization", "name": inst_name})

        metadata = {
            'title': find_text(".//r3d:repositoryName"),
            'description': find_text(".//r3d:description"),
            'identifier': [],
            'publisher': {'name': publishers if publishers else None},
            'contact': find_text(".//r3d:repositoryContact"),
        }
        metadata['identifier'].append(find_text(".//r3d:re3data.orgIdentifier"))
        metadata['identifier'].append(find_text(".//r3d:repositoryURL"))
        metadata['identifier'].append(find_text(".//r3d:repositoryIdentifier"))#e.g. fairsharing id

        #services
        #<r3d:api
        #<r3d:syndication

        # Return only non-empty values
        return {k: v for k, v in metadata.items() if v}
