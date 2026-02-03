import json
import re

import requests
from urllib.parse import urlparse
from lxml import etree
import os
import csv
import logging
from repo_harvester_server.data.country_codes import country_codes_3

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
class Re3DataHarvester:
    """
    A harvester for fetching metadata from the re3data.org registry.
    """
    logger = logging.getLogger('Re3DataHarvester')

    def __init__(self):
        self.api_url = "https://www.re3data.org/api/beta"
        self.ns = {"r3d": "http://www.re3data.org/schema/2-2"}
        self.service_mappings = self._load_service_mappings()

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
            self.logger.warning(f"Warning: Service mapping file not found at {csv_path}")
        return mappings

    def harvest(self, catalog_url):
        """
        Public method to harvest metadata for a given URL.
        It searches by the domain and then verifies the results.
        """
        self.logger.info("-- Harvesting from re3data by URL -- ")
        hostname = urlparse(catalog_url).hostname
        if not hostname:
            return None
        
        return self._search_and_verify(hostname, 'hostname')

    def harvest_by_name(self, repo_name):
        """
        Public method to harvest metadata by repository name.
        """
        self.logger.info(f"-- Harvesting from re3data by Name: {repo_name} --")
        return self._search_and_verify(repo_name, 'name')

    def _normalize_hostname(self, hostname):
        """
        Normalize a hostname by converting to lowercase and removing 'www.' prefix.
        """
        if not hostname:
            return None
        hostname = hostname.lower()
        if hostname.startswith('www.'):
            hostname = hostname[4:]
        return hostname

    def _hostnames_match(self, query_hostname, record_hostname):
        """
        Check if two hostnames match, accounting for subdomains.

        Returns True if:
        - They are equal (after normalizing)
        - One is a direct subdomain of the other (depth difference of 1)

        This is more conservative than root-domain matching, which incorrectly matched
        any hosts under the same TLD (e.g., 'data.dans.knaw.nl' with 'other.knaw.nl').

        The depth check prevents matching deep subdomains with root domains:
        - 'about.coscine.de' (3 parts) matches 'coscine.de' (2 parts) - diff 1 ✓
        - 'data.dans.knaw.nl' (4 parts) does NOT match 'knaw.nl' (2 parts) - diff 2 ✗
        - 'data.dans.knaw.nl' (4 parts) matches 'dans.knaw.nl' (3 parts) - diff 1 ✓
        """
        h1 = self._normalize_hostname(query_hostname)
        h2 = self._normalize_hostname(record_hostname)

        if not h1 or not h2:
            return False

        if h1 == h2:
            return True

        # Check if one is a subdomain of the other with max depth difference of 1
        # e.g., "about.coscine.de" should match "coscine.de"
        h1_parts = h1.split('.')
        h2_parts = h2.split('.')
        depth_diff = abs(len(h1_parts) - len(h2_parts))

        if depth_diff == 1:
            if h1.endswith('.' + h2) or h2.endswith('.' + h1):
                return True

        return False

    def _search_and_verify(self, query, search_type):
        try:
            search_url = f"{self.api_url}/repositories?query={query}"
            self.logger.info(f"Querying re3data search API: {search_url}")
            resp = requests.get(search_url, timeout=15)
            resp.raise_for_status()
            root = etree.fromstring(resp.content)
            
            # Iterate through <repository> elements in the search result list
            for repo_element in root.findall('.//repository'):
                repo_id_elem = repo_element.find('id')
                repo_name_elem = repo_element.find('name')
                
                if repo_id_elem is None or not repo_id_elem.text:
                    self.logger.warning("Found a search result with no ID, skipping.")
                    continue
                
                repo_id = repo_id_elem.text
                
                # Verification logic based on search type
                if search_type == 'name':
                    if repo_name_elem is not None and repo_name_elem.text:
                        self.logger.info(f"Verifying name match for ID {repo_id}: Query='{query}', Found='{repo_name_elem.text}'")
                        if query.lower() in repo_name_elem.text.lower():
                            self.logger.info(f"SUCCESS: Found verified re3data entry for '{query}' via name search: {repo_id}")
                            return self.harvest_by_id(repo_id)
                
                elif search_type == 'hostname':
                    # For hostname verification, we still need to fetch the full record to get the URL
                    # because the search result list doesn't include the repositoryURL.
                    repo_root = self._fetch_and_parse_record_xml(repo_id)
                    if repo_root is None:
                        continue

                    repo_main_url_element = repo_root.find('.//r3d:repositoryURL', self.ns)
                    if repo_main_url_element is not None and repo_main_url_element.text:
                        re3data_hostname = urlparse(repo_main_url_element.text).hostname

                        self.logger.info(f"Verifying hostname match for ID {repo_id}: Query='{query}', Found='{re3data_hostname}'")

                        if self._hostnames_match(query, re3data_hostname):
                            self.logger.info(f"SUCCESS: Found verified re3data entry for '{query}' via hostname search: {repo_id}")
                            return self._parse_record(repo_root)

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Re3data API request error during search for {query}: {e}")
        except etree.XMLSyntaxError as e:
            self.logger.error(f"Error parsing re3data XML during search for {query}: {e}")
            
        self.logger.warning(f"Could not find a verified re3data entry for query: '{query}'")
        return None

    def harvest_by_id(self, re3data_id):
        """
        Harvests metadata directly from re3data using its re3data.orgIdentifier.
        """
        self.logger.info(f"-- Harvesting from re3data by ID: {re3data_id} --")
        try:
            repo_root = self._fetch_and_parse_record_xml(re3data_id)
            if repo_root is not None:
                self.logger.info(f"Successfully fetched re3data entry for ID: {re3data_id}")
                return self._parse_record(repo_root)
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Re3data API request error during harvest by ID {re3data_id}: {e}")
        except etree.XMLSyntaxError as e:
            self.logger.error(f"Error parsing re3data XML during harvest by ID {re3data_id}: {e}")
        return None

    def _fetch_and_parse_record_xml(self, repo_id):
        """
        Helper method to fetch and parse the detailed XML record for a given repo_id.
        """
        try:
            repo_url = f"{self.api_url}/repository/{repo_id}"
            repo_resp = requests.get(repo_url, timeout=15)
            repo_resp.raise_for_status()
            return etree.fromstring(repo_resp.content)
        except (requests.exceptions.RequestException, etree.XMLSyntaxError) as e:
            self.logger.error(f"Failed to fetch or parse record for re3data ID {repo_id}: {e}")
            return None

    def _parse_record(self, repo_root):
        """
        Parses the detailed XML for a specific repository from re3data.
        """
        # General purpose helper for single-value text fields
        def find_text(element, path):
            node = element.find(path, self.ns)
            return node.text.strip() if node is not None and node.text else None

        # General purpose helper for multi-value text fields
        def find_all_text(element, path):
            return [node.text.strip() for node in element.findall(path, self.ns) if node.text]
        #TODO: license missing!!

        # --- Publisher / Institution Extraction (Handles Multiple) ---
        publishers = []
        for inst_element in repo_root.findall(".//r3d:institution", self.ns):
            inst_name = find_text(inst_element, 'r3d:institutionName')
            inst_country = find_text(inst_element, 'r3d:institutionCountry')
            if re.match(r'^[A-Z]{3}$', str(inst_country)):
                if inst_country in country_codes_3:
                    inst_country = country_codes_3[inst_country]
            if inst_name:
                publishers.append({"type": "org:Organization", "name": inst_name, "country": inst_country})
        contact = {}
        for contact_elem in repo_root.findall(".//r3d:repositoryContact", self.ns):
            if '@' in contact_elem.text:
                contact['email'] = contact_elem.text
            elif 'http' in contact_elem.text:
                contact['url'] = contact_elem.text
        # --- Service Extraction (Handles Multiple) ---
        services = []
        for api_elem in repo_root.findall(".//r3d:api", self.ns):
            api_type = api_elem.get('apiType')
            api_url = api_elem.text.strip() if api_elem.text else None
            if api_url:
                services.append({
                    'endpoint_uri': api_url,
                    'type': f"re3data:API:{api_type}" if api_type else "re3data:API",
                    'conforms_to': self.service_mappings.get(api_type),
                    'title': f"{api_type} API" if api_type else "API Service"
                })
        for syndication_elem in repo_root.findall(".//r3d:syndication", self.ns):
            syndication_type = syndication_elem.get('syndicationType')
            syndication_url = syndication_elem.text.strip() if syndication_elem.text else None
            if syndication_url:
                services.append({
                    'endpoint_uri': syndication_url,
                    'type': f"re3data:Syndication:{syndication_type}" if syndication_type else "re3data:Syndication",
                    'conforms_to': self.service_mappings.get(syndication_type),
                    'title': f"{syndication_type} Feed" if syndication_type else "Syndication Feed"
                })
        
        # --- Identifier Extraction (Handles Multiple) ---
        identifiers = [
            find_text(repo_root, ".//r3d:re3data.orgIdentifier"),
            find_text(repo_root, ".//r3d:repositoryURL")
        ] + find_all_text(repo_root, ".//r3d:repositoryIdentifier")


        metadata = {
            'resource_type' : 'r3d:Repository',# see: https://github.com/re3data/ontology/blob/master/r3dOntology.ttl
            'title': find_text(repo_root, ".//r3d:repositoryName"),
            'description': find_text(repo_root, ".//r3d:description"),
            'identifier': [i for i in identifiers if i],
            'publisher': publishers if publishers else None,
            'contact' : contact,
            #'contact': find_all_text(repo_root, ".//r3d:repositoryContact"),
            'services': services if services else None,
            'keywords': find_all_text(repo_root, ".//r3d:keyword"),
            'subject': find_all_text(repo_root, ".//r3d:subject")
        }
        return {k: v for k, v in metadata.items() if v}
