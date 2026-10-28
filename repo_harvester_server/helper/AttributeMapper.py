"""Find KB attribute values in harvested data with the KB's source patterns.

A source pattern is a SPARQL group graph pattern that binds ?value for the
repository ?repository. It runs on the harmonised record, with ?repository
bound to the repository, and on every raw source graph, with ?repository bound
to the graph's foaf:primaryTopic.
"""
import json
import logging

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import FOAF
from rdflib.plugins.sparql import prepareQuery

from repo_harvester_server.helper.RawGraph import NAMESPACES

logger = logging.getLogger('AttributeMapper')

# The prefixes source patterns can use. Dublin Core terms is dct only: rdflib keeps one prefix per namespace.
PREFIXES = {
    'trsp': 'https://w3id.org/trsp/',
    'edenkb': 'https://w3id.org/eosc-eden/kb#',
    'drawg': 'https://w3id.org/eosc-eden/kb/drawg#',
    'fidelis': 'https://w3id.org/eosc-eden/kb/fidelis-network#',
    'r3d': 'http://www.re3data.org/schema/4-0#',
    'fsharing': NAMESPACES['fairsharing'],
    'cts': NAMESPACES['coretrustseal'],
    'linkset': NAMESPACES['fairicat_services'],
    'meta': NAMESPACES['meta_tags'],
    'schema': 'https://schema.org/',
    'dct': 'http://purl.org/dc/terms/',
    'dcat': 'http://www.w3.org/ns/dcat#',
    'foaf': 'http://xmlns.com/foaf/0.1/',
    'vcard': 'http://www.w3.org/2006/vcard/ns#',
    'dqv': 'http://www.w3.org/ns/dqv#',
    'premis': 'http://www.loc.gov/premis/rdf/v3/',
    'prov': 'http://www.w3.org/ns/prov#',
    'skos': 'http://www.w3.org/2004/02/skos/core#',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'rdfs': 'http://www.w3.org/2000/01/rdf-schema#',
    'xsd': 'http://www.w3.org/2001/XMLSchema#',
}


def map_attributes(merged: Graph, repository: URIRef, raw_graphs: list[Graph],
                   patterns: list[tuple[str, str]]) -> dict[str, list[str | URIRef]]:
    """The values each attribute's patterns find: literals as plain strings, IRIs as URIRefs."""
    starts = [(merged, repository)] + [(g, main) for g in raw_graphs for main in g.objects(None, FOAF.primaryTopic)]
    values = {}
    for attribute, pattern in patterns:
        found = values.setdefault(attribute, [])
        try:
            query = prepareQuery(f'SELECT DISTINCT ?value WHERE {{ {pattern} }}', initNs=PREFIXES)
            for graph, start in starts:
                for (value,) in graph.query(query, initBindings={'repository': start}):
                    if isinstance(value, BNode):
                        continue
                    value = value if isinstance(value, URIRef) else str(value)
                    # An IRI and a literal with the same text are one value; rdflib does not treat them as equal.
                    if str(value) not in map(str, found):
                        found.append(value)
        except Exception as e:
            logger.warning('Skipping the source pattern of %s: %s', attribute, e)
    return {attribute: found for attribute, found in values.items() if found}


def add_attribute_values(dcat: dict, values: dict[str, list[str | URIRef]]) -> dict:
    """Write the values into the record under the full attribute IRIs, IRIs as {'@id': iri}."""
    for attribute, found in values.items():
        dcat['foaf:primaryTopic'][attribute] = [{'@id': str(v)} if isinstance(v, URIRef) else v for v in found]
    return dcat


def apply_kb_attributes(dcat: dict, repository: str, fuseki) -> dict:
    """Add the KB attribute values found for the repository to its harmonised record."""
    patterns = fuseki.get_source_patterns()
    if not patterns:
        logger.warning('KB source patterns not found in eden://kb/definitions; attribute values not mapped')
        return dcat
    merged = Graph().parse(data=json.dumps(dcat), format='json-ld')
    values = map_attributes(merged, URIRef(repository), fuseki.get_raw_graphs(repository), patterns)
    return add_attribute_values(dcat, values)
