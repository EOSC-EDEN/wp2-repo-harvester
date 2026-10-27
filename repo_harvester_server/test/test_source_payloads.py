"""Tests for keeping what each source returned next to the extracted metadata."""

import json
from unittest import mock

import requests
from lxml import etree
from rdflib import Literal, URIRef
from rdflib.namespace import FOAF

from repo_harvester_server.helper.CoreTrustSealHarvester import CoreTrustSealHarvester
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.RawGraph import xml_to_graph
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester

G = "eden://harvester/raw/re3data/https://example.org/"
R3D = "http://www.re3data.org/schema/4-0"
SCRIPT = {"@context": "https://schema.org", "@type": "DataCatalog", "name": "X"}


def test_re3data_record_keeps_repository_xml():
    xml = (f'<r3d:re3data xmlns:r3d="{R3D}"><r3d:repository>'
           "<r3d:repositoryName>X</r3d:repositoryName><r3d:pidSystem>DOI</r3d:pidSystem>"
           "</r3d:repository></r3d:re3data>")
    g = xml_to_graph(Re3DataHarvester()._parse_record(etree.fromstring(xml))["_raw"], G)
    assert g.value(g.value(URIRef(G), FOAF.primaryTopic), URIRef(R3D + "#pidSystem")) == Literal("DOI")


def test_fairsharing_result_keeps_record():
    with mock.patch.object(FAIRsharingHarvester, "_authenticate"):
        harvester = FAIRsharingHarvester()
    record = {"id": 1, "type": "fairsharing_records",
              "attributes": {"record_type": "repository",
                             "metadata": {"name": "X", "homepage": "https://example.org/"}}}
    assert harvester._parse_search_results([record], hostname_filter="example.org")["_raw"] == record


def test_coretrustseal_record_keeps_certificates():
    group = [{"validUntil": "2030-01-01", "repository": {"name": "X"}}]
    assert CoreTrustSealHarvester()._record(group)["_raw"] == {"certificates": group}


def test_embedded_jsonld_keeps_script():
    page = f'<html><head><script type="application/ld+json">{json.dumps(SCRIPT)}</script></head></html>'
    raw = MetadataHelper(catalog_html=page).get_embedded_jsonld_metadata("simple")["_raw"]
    assert json.loads(raw) == SCRIPT


def test_linked_jsonld_keeps_document():
    session = mock.Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.json.return_value = SCRIPT
    helper = MetadataHelper(session=session)
    raw = helper.get_linked_jsonld_metadata("https://example.org/ld.json", "simple")["_raw"]
    assert json.loads(raw) == SCRIPT


def test_meta_tags_keep_all_tags():
    page = ('<html><head><meta charset="utf-8"><meta name="description" content="D">'
            '<meta property="og:title" content="T"></head></html>')
    raw = MetadataHelper(catalog_html=page).get_html_meta_tags_metadata()["_raw"]
    assert raw == {"description": ["D"], "og:title": ["T"]}


def test_fairicat_keeps_linksets():
    linkset = {"linkset": [{"anchor": "https://example.org/api",
                            "service-doc": [{"href": "https://example.org/docs"}]}]}
    session = mock.Mock()
    session.get.return_value.json.return_value = linkset
    page = ('<html><head><link rel="api-catalog" type="application/linkset+json" '
            'href="https://example.org/.well-known/api-catalog"></head></html>')
    helper = MetadataHelper("https://example.org/", page, {}, session=session)
    assert helper.get_fairicat_metadata()["_raw"] == {"linksets": [linkset]}


def test_raw_payloads_are_kept_apart_from_extracted_metadata():
    session = mock.Mock()
    session.get.side_effect = requests.exceptions.ConnectionError("no network in tests")
    harvester = RepositoryHarvester("https://example.org/", session=session)
    harvester.merge_metadata({"_raw": {"og:title": ["T"]}}, "meta_tags")
    harvester.merge_metadata({"title": "X", "_raw": "<r3d:repository/>"}, "re3data")
    assert harvester.metadata == [
        {"source": "re3data", "metadata": {"title": "X", "identifier": "https://example.org/"}}]
    assert harvester.raw_payloads == {"meta_tags": [{"og:title": ["T"]}], "re3data": ["<r3d:repository/>"]}
