"""Tests for converting source payloads to RDF."""

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import FOAF, RDF

from repo_harvester_server.helper.RawGraph import (NAMESPACES, json_to_graph, jsonld_to_graph, meta_to_graph,
                                                   xml_to_graph)

G = "eden://harvester/raw/re3data/https://example.org/"
R3D = "http://www.re3data.org/schema/4-0#"
XML = ('<r3d:repository xmlns:r3d="http://www.re3data.org/schema/4-0">'
       '<!-- a comment -->'
       '<r3d:pidSystem>DOI</r3d:pidSystem>'
       '<r3d:metadataStandard><r3d:metadataStandardName metadataStandardScheme="DCC">'
       'Dublin Core</r3d:metadataStandardName></r3d:metadataStandard></r3d:repository>')


def test_xml_elements_become_predicates_in_their_namespace():
    g = xml_to_graph(XML, G)
    main = g.value(URIRef(G), FOAF.primaryTopic)
    assert g.value(main, URIRef(R3D + "pidSystem")) == Literal("DOI")
    standard = g.value(main, URIRef(R3D + "metadataStandard"))
    assert g.value(standard, URIRef(R3D + "metadataStandardName")) == Literal("Dublin Core")
    assert (None, URIRef(R3D + "metadataStandardScheme"), None) not in g


def test_json_keys_become_predicates_and_nulls_are_left_out():
    g = json_to_graph({"attributes": {"metadata": {"name": "X"}}, "gone": None, "n": 3},
                      NAMESPACES["fairsharing"], G)
    main = g.value(URIRef(G), FOAF.primaryTopic)
    ns = NAMESPACES["fairsharing"]
    metadata = g.value(g.value(main, URIRef(ns + "attributes")), URIRef(ns + "metadata"))
    assert g.value(metadata, URIRef(ns + "name")) == Literal("X")
    assert g.value(main, URIRef(ns + "gone")) is None
    assert g.value(main, URIRef(ns + "n")) == Literal(3)


def test_jsonld_schema_org_http_context_becomes_https():
    g = jsonld_to_graph('{"@context": "http://schema.org", "@type": "DataCatalog", "name": "X"}', G)
    main = g.value(URIRef(G), FOAF.primaryTopic)
    assert g.value(main, URIRef("https://schema.org/name")) == Literal("X")


def test_jsonld_schema_org_http_iris_become_https():
    g = jsonld_to_graph('{"@context": {"@vocab": "http://schema.org/"}, "@type": "DataCatalog", "name": "X"}', G)
    main = g.value(URIRef(G), FOAF.primaryTopic)
    assert g.value(main, RDF.type) == URIRef("https://schema.org/DataCatalog")
    assert g.value(main, URIRef("https://schema.org/name")) == Literal("X")


def test_jsonld_relative_iris_resolve_against_the_repository_url():
    g = jsonld_to_graph('{"@context": "https://schema.org", "@id": "#catalog", "@type": "DataCatalog"}', G)
    assert g.value(URIRef(G), FOAF.primaryTopic) == URIRef("https://example.org/#catalog")


def test_jsonld_remote_context_is_refused_without_fetching():
    with pytest.raises(ValueError, match="http://127.0.0.1:9/context"):
        jsonld_to_graph('{"@context": ["https://schema.org", "http://127.0.0.1:9/context"], "name": "X"}', G)


def test_meta_tags_become_literals():
    g = meta_to_graph({"description": ["D"], "og:title": ["T"]}, G)
    main = g.value(URIRef(G), FOAF.primaryTopic)
    assert g.value(main, URIRef(NAMESPACES["meta_tags"] + "og%3Atitle")) == Literal("T")
