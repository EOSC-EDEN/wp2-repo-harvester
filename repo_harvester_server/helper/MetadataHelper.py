import json
import logging
import re
from pathlib import Path

import rdflib
from jsonschema.exceptions import ValidationError
from rdflib import RDF, DCAT, DC, DCTERMS, FOAF, SKOS, URIRef
from lxml import html as lxml_html
import os
from repo_harvester_server.helper.GraphHelper import JSONGraph
from repo_harvester_server.helper.SignPostingHelper import SignPostingHelper
from repo_harvester_server.helper.JMESPATHQueries import SERVICE_INFO_QUERY, REPO_INFO_QUERY, DCAT_EXPORT_QUERY
from jsonschema import validate
import jmespath
import requests

# Define Namespaces
VCARD = rdflib.Namespace("http://www.w3.org/2006/vcard/ns#")
ORG = rdflib.Namespace("http://www.w3.org/ns/org#")
OBO = rdflib.Namespace("http://purl.obolibrary.org/obo/")

# Define both HTTP and HTTPS for Schema.org
SDO_HTTPS = rdflib.Namespace("https://schema.org/")
SDO_HTTP = rdflib.Namespace("http://schema.org/")

# Custom DCAT term - explicitly define as URIRef to avoid UserWarning
DCAT_IN_CATALOG = URIRef("http://www.w3.org/ns/dcat#inCatalog")

logging.getLogger('rdflib.term').setLevel(logging.ERROR)

class MetadataHelper:
    def __init__(self, catalog_url, catalog_html=None, catalog_header=None):
        # Get the directory where the current script is located
        helper_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the absolute path to the xslt file
        self.xslt_path = os.path.normpath(os.path.join(helper_dir, '..', 'xslt', 'rdf2json.xslt'))
        self.catalog_url = catalog_url
        self.catalog_html = catalog_html
        self.catalog_header = catalog_header
        self.signposting_helper = SignPostingHelper(self.catalog_url, self.catalog_html, self.catalog_header)

    def _fuzzy_value(self, g, subject, property_names):
        """Robustly finds a value by matching property URI endings."""
        if isinstance(property_names, str):
            property_names = [property_names]
            
        # 1. Exact matches (Fast)
        for prop in property_names:
            v = g.value(subject, SDO_HTTPS[prop]) or g.value(subject, SDO_HTTP[prop])
            if v: return v

        # 2. Suffix check (Robust)
        for s, p, o in g.triples((subject, None, None)):
            str_p = str(p)
            for prop in property_names:
                if str_p.endswith(f"/{prop}") or str_p.endswith(f"#{prop}"):
                    return o
        return None

    def _fuzzy_objects(self, g, subject, property_names):
        results = []
        if isinstance(property_names, str): property_names = [property_names]
        
        # Exact + Suffix
        for s, p, o in g.triples((subject, None, None)):
            str_p = str(p)
            for prop in property_names:
                if str_p.endswith(f"/{prop}") or str_p.endswith(f"#{prop}"):
                    results.append(o)
        return results

    def get_html_meta_tags_metadata(self):
        metadata = {}
        if not isinstance(self.catalog_html, str) or not self.catalog_html: return metadata
        try:
            doc = lxml_html.fromstring(self.catalog_html)
            desc = doc.xpath('//meta[@name="description"]/@content')
            if desc: metadata['description'] = desc[0].strip()
            pub = doc.xpath('//meta[@name="publisher"]/@content')
            if pub: metadata['publisher'] = pub[0].strip()
            tit = doc.xpath('//meta[@name="title"]/@content')
            if tit: metadata['title'] = tit[0].strip()
        except Exception: pass
        return {k: v for k, v in metadata.items() if v}

    def _extract_publisher(self, g, resource_node):
        # 1. Look for explicit Publisher/Provider/Creator properties
        publisher_node = g.value(resource_node, DCTERMS.publisher) or \
                         g.value(resource_node, DC.publisher) or \
                         self._fuzzy_value(g, resource_node, ['publisher', 'provider', 'creator', 'author'])
        
        # 2. Last Resort: Look for ANY linked Organization
        if not publisher_node:
            for s, p, o in g.triples((resource_node, None, None)):
                # Check if object is an Organization
                if (o, RDF.type, ORG.Organization) in g or \
                   (o, RDF.type, SDO_HTTPS.Organization) in g or \
                   (o, RDF.type, SDO_HTTP.Organization) in g or \
                   (o, RDF.type, FOAF.Organization) in g:
                    publisher_node = o
                    break

        if not publisher_node:
            return None

        pub_data = {}
        if isinstance(publisher_node, rdflib.URIRef):
            pub_data['id'] = str(publisher_node)
            
        p_type = g.value(publisher_node, RDF.type)
        pub_data['type'] = str(p_type) if p_type else "org:Organization"

        name = g.value(publisher_node, FOAF.name) or \
               self._fuzzy_value(g, publisher_node, ['name', 'legalName'])
        
        if name:
            pub_data['name'] = str(name)
        elif isinstance(publisher_node, rdflib.Literal):
            pub_data['name'] = str(publisher_node)

        # Country
        address = self._fuzzy_value(g, publisher_node, 'address') or \
                  g.value(publisher_node, VCARD.hasAddress)
        country = None
        if address:
            country = self._fuzzy_value(g, address, 'addressCountry') or \
                      g.value(address, VCARD['country-name'])
        
        if not country:
            country = g.value(publisher_node, VCARD['country-name'])

        if country:
            pub_data['country'] = str(country)

        return pub_data

    def _extract_processes(self, g, service_node):
        process_list = []
        CONTAINS_PROCESS = OBO['BFO_0000067']
        for proc in g.objects(service_node, CONTAINS_PROCESS):
            proc_dict = {'id': str(proc) if isinstance(proc, rdflib.URIRef) else None}
            label = g.value(proc, SKOS.prefLabel) or \
                    self._fuzzy_value(g, proc, 'name') or \
                    g.value(proc, DCTERMS.title)
            if label: proc_dict['title'] = str(label)
            notation = g.value(proc, SKOS.notation)
            if notation: proc_dict['label'] = str(notation)
            process_list.append(proc_dict)
        return process_list

    def _extract_services(self, g, catalog_node):
        services_list = []
        service_nodes = list(g.objects(catalog_node, DCAT.service)) + \
                        self._fuzzy_objects(g, catalog_node, 'service')
        
        for s, p, o in g.triples((None, DCAT_IN_CATALOG, catalog_node)):
            if s not in service_nodes: service_nodes.append(s)

        for svc in service_nodes:
            svc_dict = {'id': str(svc) if isinstance(svc, rdflib.URIRef) else None}
            t = g.value(svc, RDF.type)
            svc_dict['type'] = str(t) if t else 'dcat:DataService'
            
            title = g.value(svc, DCTERMS.title) or self._fuzzy_value(g, svc, 'name')
            if title: svc_dict['title'] = str(title)

            endpoint = g.value(svc, DCAT.endpointURL) or self._fuzzy_value(g, svc, 'url')
            if endpoint: svc_dict['endpointURL'] = str(endpoint)
            
            processes = self._extract_processes(g, svc)
            if processes: svc_dict['containsProcess'] = processes

            desc = g.value(svc, DCTERMS.description) or \
                   g.value(svc, DCAT.endpointDescription) or \
                   self._fuzzy_value(g, svc, 'description')
            if desc: svc_dict['description'] = str(desc)
            
            doc = g.value(svc, FOAF.page) or self._fuzzy_value(g, svc, 'documentation')
            if doc: svc_dict['documentation'] = str(doc)

            conforms = g.value(svc, DCTERMS.conformsTo)
            if conforms: svc_dict['conformsTo'] = str(conforms)

            fmt = g.value(svc, DCTERMS.format)
            if fmt: svc_dict['format'] = str(fmt)

            title = g.value(svc, DCTERMS.title) or self._fuzzy_value(g, svc, 'name')
            if title: svc_dict['title'] = str(title)

            svc_dict['conforms_to'] = svc_dict.get('conformsTo') or  svc_dict.get('documentation') or svc_dict.get('description') or None
            svc_dict['endpoint_uri'] = svc_dict.get('endpointURL')
            
            services_list.append(svc_dict)
        return services_list

    def get_jsonld_metadata(self, jstr):
        metadata = {}
        if not isinstance(jstr, str): return metadata
        try:
            g = rdflib.ConjunctiveGraph()
            g.parse(data=jstr, format='json-ld')
            
            catalog_node = None
            
            # 1. Type Check
            for s, p, o in g.triples((None, RDF.type, None)):
                obj_str = str(o)
                if obj_str.endswith("Catalog") or obj_str.endswith("Repository"):
                    catalog_node = s; break
            
            # 2. Fallback
            if not catalog_node:
                for s, p, o in g.triples((None, RDF.type, None)):
                    if str(o).endswith("/WebSite"): catalog_node = s; break
            
            # 3. Name/Title Check
            if not catalog_node:
                found_name = self._fuzzy_value(g, None, 'name')
                if found_name:
                    for s, p, o in g.triples((None, None, found_name)): catalog_node = s; break

            if catalog_node:
                node_id = str(catalog_node) if isinstance(catalog_node, rdflib.URIRef) else None
                title = g.value(catalog_node, DCTERMS.title) or \
                        self._fuzzy_value(g, catalog_node, 'name') or \
                        g.value(catalog_node, FOAF.name)
                if title: metadata['title'] = str(title)

                desc = g.value(catalog_node, DCTERMS.description) or \
                       self._fuzzy_value(g, catalog_node, 'description')
                if desc: metadata['description'] = str(desc)

                lp = g.value(catalog_node, DCAT.landingPage) or \
                     self._fuzzy_value(g, catalog_node, 'url') or \
                     g.value(catalog_node, FOAF.homepage)
                if lp: metadata['landingPage'] = str(lp)
                
                if node_id: metadata['id'] = node_id
                elif 'landingPage' in metadata: metadata['id'] = metadata['landingPage']

                pub_data = self._extract_publisher(g, catalog_node)
                if pub_data: metadata['publisher'] = pub_data

                services = self._extract_services(g, catalog_node)
                if services: metadata['services'] = services
        except Exception as e:
            print(f"Error processing JSON-LD: {e}")
        return metadata

    def get_embedded_jsonld_metadata(self,  mode = 'rdflib'):
        metadata = {}
        if not isinstance(self.catalog_html, str): return metadata
        try:
            doc = lxml_html.fromstring(self.catalog_html)
            scripts = doc.xpath('//script[@type="application/ld+json"]/text()')
            for script_content in scripts:
                if not script_content.strip(): continue
                try:
                    json.loads(script_content)
                    if mode == 'rdflib':
                        extracted = self.get_jsonld_metadata(script_content)
                    else:
                        extracted = self.get_jsonld_metadata_simple(script_content)
                    metadata.update(extracted)
                except json.JSONDecodeError: continue
        except Exception as e:
            print(f"Loading embedded JSON-LD Error: {e}")
        return metadata
    
    def get_linked_jsonld_metadata(self, typed_link, mode = 'rdflib'):
        metadata = {}
        if 'http' in str(typed_link):
            try:
                import requests
                resp = requests.get(typed_link, timeout=10)
                if resp.status_code == 200:
                    try:
                        ljson_str = json.dumps(resp.json())
                        if mode == 'rdflib':
                            metadata = self.get_jsonld_metadata(ljson_str)
                        else:
                            metadata = self.get_jsonld_metadata_simple(ljson_str)
                    except json.JSONDecodeError: pass
            except Exception: pass
        return metadata

    def get_sitemap_service_metadata(self):
        metadata = {}
        sitemap_services = []
        if self.catalog_url:
            try:
                r = requests.get(str(self.catalog_url).rstrip('/')+'/robots.txt')
                if r.status_code == 200:
                    m = re.search(r'^Sitemap:\s*(\S+)', r.text, re.MULTILINE)
                    if m:
                        sitemap_services.append({
                            'endpoint_uri': m.group(1),
                            'conforms_to': 'https://www.sitemaps.org/protocol.html',
                            'output_format': 'application/xml'
                        })
            except Exception as e:
                print('FAILED TO GET SITEMAP SERVICE METADATA: ', e)
            if sitemap_services:
                metadata['services'] = sitemap_services
        return metadata

    def get_feed_metadata(self):
        metadata = {}
        services = []
        feed_types = {'application/rss+xml':'https://www.rssboard.org/rss-specification',
                      'application/atom+xml': 'https://www.ietf.org/rfc/rfc4287.txt'}
        feed_links = self.signposting_helper.get_links(rel='alternate', type=list(feed_types.keys()))
        for api_link in feed_links:
            services.append({
                'endpoint_uri' : api_link.get('link'),
                'conforms_to' : feed_types.get(api_link.get('type')),
                'title' : api_link.get('title'),
                'output_format' :  api_link.get('type')
            })
        if services:
            metadata['services'] = services
        return metadata

    def get_fairicat_metadata(self):
        metadata = {}
        services = []
        fairicat_api_links = self.signposting_helper.get_links(rel=['service-doc', 'service-meta'])
        
        # Use a dictionary to group by anchor
        grouped_services = {}
        for api_link in fairicat_api_links:
            anchor = api_link.get('anchor')
            if anchor not in grouped_services:
                grouped_services[anchor] = {'endpoint_uri': anchor}
            
            if api_link.get('rel') == 'service-doc':
                grouped_services[anchor]['conforms_to'] = api_link.get('link')
                if api_link.get('title'):
                    grouped_services[anchor]['title'] = api_link.get('title')
            if api_link.get('rel') == 'service-meta':
                grouped_services[anchor]['service_desc'] = api_link.get('link')
                if api_link.get('type'):
                    grouped_services[anchor]['output_format'] = api_link.get('type')
        
        if grouped_services:
            metadata['services'] = list(grouped_services.values())
        return metadata

    def get_jsonld_metadata_simple(self, jstr):
        # This method used the GraphHelper and JMESPATH instead of RDFlib
        metadata = {}
        if isinstance(jstr, str):
            sg = JSONGraph()
            sg.parse(jstr)
            metadata = sg.query(REPO_INFO_QUERY)
            services =[]
            for service_node in sg.getNodesByType(['Service', 'WebAPI', 'DataService','SearchAction']):
                service_res = jmespath.search(SERVICE_INFO_QUERY, service_node)
                if service_res.get('endpoint_uri'):
                    if service_res.get('type') == 'SearchAction':
                        service_res['output_format'] = 'text/html'
                        service_res['conforms_to'] = 'https://www.ietf.org/rfc/rfc2616' #http (default)
                    services.append(service_res)
            if services:
                metadata['services'] = services
        return metadata

    def validate(self,  data, schema = None):
        if not schema:
            schema_path = Path(__file__).resolve().parent.parent / 'schema' / 'repo_schema.json'
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        try:
            validate(instance=data, schema=schema)
        except ValidationError as e:
            print(e.message)

    def export(self, metadata):
        return jmespath.search(data=metadata, expression = DCAT_EXPORT_QUERY)