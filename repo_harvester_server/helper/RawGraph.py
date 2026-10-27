"""Convert what a source returned into RDF, keeping every field.

Each graph marks its main node, the repository, with
<graph IRI> foaf:primaryTopic <main node>.
"""
import json
import logging
import re
from urllib.parse import quote

from lxml import etree
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import FOAF, RDF, SDO
from rdflib.term import Node

logger = logging.getLogger('RawGraph')

RAW_GRAPH_PREFIX = 'eden://harvester/raw/'
NAMESPACES = {
    'fairsharing': 'http://fairsharing.org/model/fairsharing_record_schema#',
    'coretrustseal': 'https://w3id.org/eosc-eden/raw/coretrustseal#',
    'fairicat_services': 'https://w3id.org/eosc-eden/raw/linkset#',
    'meta_tags': 'https://w3id.org/eosc-eden/raw/meta#',
}
ABSOLUTE_IRI = re.compile(r'^https?://')
SCHEMA_ORG_CONTEXT = re.compile(r'^https?://(www\.)?schema\.org(/.*)?$')
SCHEMA_ORG_IRI = re.compile(r'^https?://(www\.)?schema\.org/')


def _new_graph(graph_iri: str) -> tuple[Graph, BNode]:
    g = Graph()
    main = BNode()
    g.add((URIRef(graph_iri), FOAF.primaryTopic, main))
    return g, main


def _elements(element) -> list:
    """Child elements, without comments and processing instructions."""
    return [child for child in element if isinstance(child.tag, str)]


def _xml_predicate(name: str, namespace: str) -> URIRef:
    """Namespace plus local name, joined by # unless the namespace ends with / or #."""
    qname = etree.QName(name)
    namespace = qname.namespace or namespace
    separator = '' if namespace.endswith(('/', '#')) else '#'
    return URIRef(namespace + separator + qname.localname)


def _add_element(g: Graph, node: BNode, element) -> None:
    namespace = etree.QName(element).namespace or ''
    for name, value in element.attrib.items():
        g.add((node, _xml_predicate(name, namespace), Literal(value)))
    for child in _elements(element):
        predicate = _xml_predicate(child.tag, namespace)
        if _elements(child):
            child_node = BNode()
            g.add((node, predicate, child_node))
            _add_element(g, child_node, child)
        elif child.text and child.text.strip():
            g.add((node, predicate, Literal(child.text.strip())))


def xml_to_graph(xml: str, graph_iri: str) -> Graph:
    g, main = _new_graph(graph_iri)
    _add_element(g, main, etree.fromstring(xml.encode('utf-8')))
    return g


def _add_value(g: Graph, node: BNode, predicate: URIRef, value, namespace: str) -> None:
    if isinstance(value, list):
        for item in value:
            _add_value(g, node, predicate, item, namespace)
    elif isinstance(value, dict):
        child = BNode()
        g.add((node, predicate, child))
        _add_object(g, child, value, namespace)
    elif value is not None:
        g.add((node, predicate, Literal(value)))


def _add_object(g: Graph, node: BNode, data: dict, namespace: str) -> None:
    for key, value in data.items():
        predicate = URIRef(key if ABSOLUTE_IRI.match(key) else namespace + quote(key, safe=''))
        _add_value(g, node, predicate, value, namespace)


def json_to_graph(data: dict, namespace: str, graph_iri: str) -> Graph:
    g, main = _new_graph(graph_iri)
    _add_object(g, main, data, namespace)
    return g


def _schema_org_context(context):
    if isinstance(context, list):
        return [_schema_org_context(item) for item in context]
    if isinstance(context, str) and SCHEMA_ORG_CONTEXT.match(context):
        return {'@vocab': 'https://schema.org/'}
    return context


def _local_contexts(node):
    """Replace schema.org context URLs with a local vocabulary, so rdflib does not fetch them."""
    if isinstance(node, list):
        return [_local_contexts(item) for item in node]
    if isinstance(node, dict):
        return {key: _schema_org_context(value) if key == '@context' else _local_contexts(value)
                for key, value in node.items()}
    return node


def _context_urls(node) -> list[str]:
    """Every context URL in a JSON-LD document, at any depth."""
    urls = []
    if isinstance(node, list):
        for item in node:
            urls += _context_urls(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key in ('@context', '@import'):
                urls += [v for v in (value if isinstance(value, list) else [value]) if isinstance(v, str)]
            urls += _context_urls(value)
    return urls


def _https_schema_org(term: Node) -> Node:
    return URIRef(SCHEMA_ORG_IRI.sub('https://schema.org/', term)) if isinstance(term, URIRef) else term


def main_node(g: Graph) -> Node | None:
    """The repository in page JSON-LD: a catalog or repository, else a website, else a named node."""
    for suffixes in (('Catalog', 'Repository'), ('WebSite',)):
        for subject, type_ in g.subject_objects(RDF.type):
            if str(type_).endswith(suffixes):
                return subject
    return next(g.subjects(SDO.name), None)


def jsonld_to_graph(jsonld: str, graph_iri: str) -> Graph:
    # The graph IRI ends with the repository URL, the page the JSON-LD comes from. Without a base,
    # rdflib resolves relative IRIs against the working directory.
    page = graph_iri[len(RAW_GRAPH_PREFIX):].split('/', 1)[1]
    data = _local_contexts(json.loads(jsonld))
    # rdflib would fetch any other context URL itself, outside the harvester's guarded session.
    # shortcut: such a payload gets no raw graph; fetch its contexts through the guarded session if a pattern needs them.
    remote = _context_urls(data)
    if remote:
        raise ValueError(f"remote JSON-LD contexts are not fetched: {', '.join(remote)}")
    parsed = Graph().parse(data=json.dumps(data), format='json-ld', base=page)
    g = Graph()
    for triple in parsed:
        g.add(tuple(_https_schema_org(term) for term in triple))
    main = main_node(g)
    if main is not None:
        g.add((URIRef(graph_iri), FOAF.primaryTopic, main))
    return g


def meta_to_graph(tags: dict[str, list[str]], graph_iri: str) -> Graph:
    g, main = _new_graph(graph_iri)
    for name, values in tags.items():
        for value in values:
            g.add((main, URIRef(NAMESPACES['meta_tags'] + quote(name, safe='')), Literal(value)))
    return g


def raw_graph(source: str, payloads: list, graph_iri: str) -> Graph:
    """One source's payloads as one graph; a payload that cannot be converted is skipped with a warning."""
    g = Graph()
    for payload in payloads:
        try:
            if source in ('embedded_jsonld', 'linked_jsonld'):
                g += jsonld_to_graph(payload, graph_iri)
            elif source == 're3data':
                g += xml_to_graph(payload, graph_iri)
            elif source == 'meta_tags':
                g += meta_to_graph(payload, graph_iri)
            else:
                g += json_to_graph(payload, NAMESPACES[source], graph_iri)
        except Exception as e:
            logger.warning('Skipping a %s payload that cannot be converted: %s', source, e)
    return g
