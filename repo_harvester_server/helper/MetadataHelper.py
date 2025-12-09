import json
import logging
import rdflib
from rdflib import RDF, DCAT, DC, DCTERMS, FOAF, SKOS
from lxml import html as lxml_html

# Define Namespaces
VCARD = rdflib.Namespace("http://www.w3.org/2006/vcard/ns#")
ORG = rdflib.Namespace("http://www.w3.org/ns/org#")
OBO = rdflib.Namespace("http://purl.obolibrary.org/obo/")

# Define both HTTP and HTTPS for Schema.org
SDO_HTTPS = rdflib.Namespace("https://schema.org/")
SDO_HTTP = rdflib.Namespace("http://schema.org/")

DCAT_IN_CATALOG = DCAT['inCatalog']

logging.getLogger('rdflib.term').setLevel(logging.ERROR)

class MetadataHelper:
    def __init__(self):
        pass

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

    def get_html_meta_tags_metadata(self, html_content):
        metadata = {}
        if not isinstance(html_content, str) or not html_content: return metadata
        try:
            doc = lxml_html.fromstring(html_content)
            desc = doc.xpath('//meta[@name="description"]/@content')
            if desc: metadata['description'] = desc[0].strip()
            auth = doc.xpath('//meta[@name="author"]/@content')
            if auth: metadata['publisher'] = {"name": auth[0].strip()}
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

    def get_embedded_jsonld_metadata(self, html_content):
        metadata = {}
        if not isinstance(html_content, str): return metadata
        try:
            doc = lxml_html.fromstring(html_content)
            scripts = doc.xpath('//script[@type="application/ld+json"]/text()')
            for script_content in scripts:
                if not script_content.strip(): continue
                try:
                    json.loads(script_content)
                    extracted = self.get_jsonld_metadata(script_content)
                    metadata.update(extracted)
                except json.JSONDecodeError: continue
        except Exception as e:
            print(f"Loading embedded JSON-LD Error: {e}")
        return metadata
    
    def get_linked_jsonld_metadata(self, typed_link):
        metadata = {}
        if 'http' in str(typed_link):
            try:
                import requests
                resp = requests.get(typed_link, timeout=10)
                if resp.status_code == 200:
                    try:
                        ljson_str = json.dumps(resp.json())
                        metadata = self.get_jsonld_metadata(ljson_str)
                    except json.JSONDecodeError: pass
            except Exception: pass
        return metadata