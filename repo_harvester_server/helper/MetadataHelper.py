import json
import logging
import rdflib
from rdflib import RDF, DCAT, DC, DCTERMS, FOAF, SKOS
from lxml import html as lxml_html

# Define Namespaces
VCARD = rdflib.Namespace("http://www.w3.org/2006/vcard/ns#")
ORG = rdflib.Namespace("http://www.w3.org/ns/org#")
OBO = rdflib.Namespace("http://purl.obolibrary.org/obo/")

# Define both HTTP and HTTPS for Schema.org to be absolutely safe
SDO_HTTPS = rdflib.Namespace("https://schema.org/")
SDO_HTTP = rdflib.Namespace("http://schema.org/")

# Suppress rdflib warnings
logging.getLogger('rdflib.term').setLevel(logging.ERROR)

class MetadataHelper:
    def __init__(self):
        pass

    def _get_sdo_value(self, g, subject, property_name):
        """Helper to check both http and https versions of a Schema.org property"""
        return g.value(subject, SDO_HTTPS[property_name]) or \
               g.value(subject, SDO_HTTP[property_name])

    def _get_sdo_objects(self, g, subject, property_name):
        """Helper to get objects for both http and https versions"""
        return list(g.objects(subject, SDO_HTTPS[property_name])) + \
               list(g.objects(subject, SDO_HTTP[property_name]))

    def get_html_meta_tags_metadata(self, html_content):
        metadata = {}
        if not isinstance(html_content, str) or not html_content:
            return metadata

        try:
            doc = lxml_html.fromstring(html_content)
            description = doc.xpath('//meta[@name="description"]/@content')
            if description:
                metadata['description'] = description[0].strip()

            author = doc.xpath('//meta[@name="author"]/@content')
            if author:
                metadata['publisher'] = {"name": author[0].strip()}

        except Exception:
            pass

        return {k: v for k, v in metadata.items() if v}

    def _extract_publisher(self, g, resource_node):
        # Check DCT, DC, SDO (HTTPS), SDO (HTTP)
        publisher_node = g.value(resource_node, DCTERMS.publisher) or \
                         g.value(resource_node, DC.publisher) or \
                         self._get_sdo_value(g, resource_node, 'publisher')
        
        if not publisher_node:
            return None

        pub_data = {}
        if isinstance(publisher_node, rdflib.URIRef):
            pub_data['id'] = str(publisher_node)
            
        p_type = g.value(publisher_node, RDF.type)
        pub_data['type'] = str(p_type) if p_type else "org:Organization"

        name = g.value(publisher_node, FOAF.name) or \
               self._get_sdo_value(g, publisher_node, 'name') or \
               self._get_sdo_value(g, publisher_node, 'legalName')
        
        if name:
            pub_data['name'] = str(name)
        elif isinstance(publisher_node, rdflib.Literal):
            pub_data['name'] = str(publisher_node)

        # Country extraction
        address = self._get_sdo_value(g, publisher_node, 'address') or \
                  g.value(publisher_node, VCARD.hasAddress)
        country = None
        if address:
            country = self._get_sdo_value(g, address, 'addressCountry') or \
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
            proc_dict = {
                'id': str(proc) if isinstance(proc, rdflib.URIRef) else None
            }
            label = g.value(proc, SKOS.prefLabel) or \
                    self._get_sdo_value(g, proc, 'name') or \
                    g.value(proc, DCTERMS.title)
            if label: proc_dict['title'] = str(label)
            
            notation = g.value(proc, SKOS.notation)
            if notation: proc_dict['label'] = str(notation)

            process_list.append(proc_dict)
        return process_list

    def _extract_services(self, g, catalog_node):
        services_list = []
        
        # 1. Direct Links
        service_nodes = list(g.objects(catalog_node, DCAT.service)) + \
                        self._get_sdo_objects(g, catalog_node, 'service')
        
        # 2. Reverse Links (Service inCatalog Catalog)
        # Use safe access for DCAT.inCatalog
        dcat_in_catalog = DCAT['inCatalog']
        for s, p, o in g.triples((None, dcat_in_catalog, catalog_node)):
            if s not in service_nodes:
                service_nodes.append(s)

        for svc in service_nodes:
            svc_dict = {
                'id': str(svc) if isinstance(svc, rdflib.URIRef) else None
            }
            
            t = g.value(svc, RDF.type)
            svc_dict['type'] = str(t) if t else 'dcat:DataService'

            title = g.value(svc, DCTERMS.title) or self._get_sdo_value(g, svc, 'name')
            if title: svc_dict['title'] = str(title)

            endpoint = g.value(svc, DCAT.endpointURL) or self._get_sdo_value(g, svc, 'url')
            if endpoint: svc_dict['endpointURL'] = str(endpoint)
            
            processes = self._extract_processes(g, svc)
            if processes:
                svc_dict['containsProcess'] = processes

            desc = g.value(svc, DCTERMS.description) or \
                   g.value(svc, DCAT.endpointDescription) or \
                   self._get_sdo_value(g, svc, 'description')
            if desc: svc_dict['description'] = str(desc)
            
            doc = g.value(svc, FOAF.page) or self._get_sdo_value(g, svc, 'documentation')
            if doc: svc_dict['documentation'] = str(doc)

            conforms = g.value(svc, DCTERMS.conformsTo)
            if conforms: svc_dict['conformsTo'] = str(conforms)
            
            fmt = g.value(svc, DCTERMS.format)
            if fmt: svc_dict['format'] = str(fmt)

            services_list.append(svc_dict)
            
        return services_list

    def get_jsonld_metadata(self, jstr):
        metadata = {}
        if not isinstance(jstr, str):
            return metadata

        try:
            g = rdflib.ConjunctiveGraph()
            g.parse(data=jstr, format='json-ld')
            
            # Skip the "fix_namespace" function because we explicitly query both http and https

            catalog_node = None
            
            # 1. Try finding explicit Catalog types
            for s in g.subjects(RDF.type, DCAT.Catalog):
                catalog_node = s
                break
            
            if not catalog_node:
                # Check both HTTP and HTTPS types
                for s in g.subjects(RDF.type, SDO_HTTPS.DataCatalog):
                    catalog_node = s; break
                if not catalog_node:
                    for s in g.subjects(RDF.type, SDO_HTTP.DataCatalog):
                        catalog_node = s; break

            # 2. Broader Fallback
            if not catalog_node:
                 for s in g.subjects(RDF.type, SDO_HTTPS.WebSite): catalog_node = s; break
                 if not catalog_node:
                     for s in g.subjects(RDF.type, SDO_HTTP.WebSite): catalog_node = s; break

            # 3. Last Resort: Title/Name
            if not catalog_node:
                for s, p, o in g.triples((None, DCTERMS.title, None)): catalog_node = s; break
                if not catalog_node:
                    for s, p, o in g.triples((None, SDO_HTTPS.name, None)): catalog_node = s; break
                    if not catalog_node:
                        for s, p, o in g.triples((None, SDO_HTTP.name, None)): catalog_node = s; break

            if catalog_node:
                # ID Handling: If BNode, fallback to URL/LandingPage
                node_id = str(catalog_node) if isinstance(catalog_node, rdflib.URIRef) else None
                
                title = g.value(catalog_node, DCTERMS.title) or \
                        self._get_sdo_value(g, catalog_node, 'name') or \
                        g.value(catalog_node, FOAF.name)
                if title: metadata['title'] = str(title)

                desc = g.value(catalog_node, DCTERMS.description) or \
                       self._get_sdo_value(g, catalog_node, 'description')
                if desc: metadata['description'] = str(desc)

                lp = g.value(catalog_node, DCAT.landingPage) or \
                     self._get_sdo_value(g, catalog_node, 'url') or \
                     g.value(catalog_node, FOAF.homepage)
                if lp: metadata['landingPage'] = str(lp)
                
                # Finalize ID
                if node_id:
                    metadata['id'] = node_id
                elif 'landingPage' in metadata:
                    metadata['id'] = metadata['landingPage']

                pub_data = self._extract_publisher(g, catalog_node)
                if pub_data:
                    metadata['publisher'] = pub_data

                services = self._extract_services(g, catalog_node)
                if services:
                    metadata['services'] = services

        except Exception as e:
            print(f"Error processing JSON-LD: {e}")

        return metadata

    def get_embedded_jsonld_metadata(self, html_content):
        metadata = {}
        if not isinstance(html_content, str):
            return metadata

        try:
            doc = lxml_html.fromstring(html_content)
            scripts = doc.xpath('//script[@type="application/ld+json"]/text()')
            
            for script_content in scripts:
                if not script_content.strip():
                    continue
                try:
                    json.loads(script_content)
                    extracted = self.get_jsonld_metadata(script_content)
                    metadata.update(extracted)
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Loading embedded JSON-LD Error: {e}")
            
        return metadata