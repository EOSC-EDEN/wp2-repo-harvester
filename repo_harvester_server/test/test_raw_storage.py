"""Tests for storing what each source returned as a raw graph."""

from unittest import mock

from rdflib import Graph, Literal, URIRef

from repo_harvester_server.helper import FUSEKIHelper as fuseki_module
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper
from repo_harvester_server.helper.RawGraph import raw_graph
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester

G = "eden://harvester/raw/re3data/https://example.org/"
R3D = "http://www.re3data.org/schema/4-0"
XML = f'<r3d:repository xmlns:r3d="{R3D}"><r3d:pidSystem>DOI</r3d:pidSystem></r3d:repository>'
PID_SYSTEM = (None, URIRef(R3D + "#pidSystem"), Literal("DOI"))


def test_save_raw_graphs_writes_one_graph_per_source():
    harvester = object.__new__(RepositoryHarvester)
    harvester.catalog_url = "https://example.org/"
    harvester.fuseki = mock.Mock()
    assert harvester.save_raw_graphs({"re3data": [XML], "coretrustseal": ["not a record"]}) == [G]
    graph_iri, data = harvester.fuseki.save.call_args.args
    assert graph_iri == G
    assert PID_SYSTEM in Graph().parse(data=data, format="json-ld")


def test_failed_payload_is_skipped_with_warning(caplog):
    g = raw_graph("re3data", ["<not xml", XML], G)
    assert PID_SYSTEM in g
    assert any(r.levelname == "WARNING" and "re3data" in r.getMessage() for r in caplog.records)


def test_merge_input_excludes_raw_graphs():
    with mock.patch.object(fuseki_module, "SPARQLWrapper") as wrapper:
        FUSEKIHelper().get_repo_graphs("https://example.org/")
    query = wrapper.return_value.setQuery.call_args.args[0]
    assert 'FILTER(!STRSTARTS(STR(?g), "eden://harvester/raw/"))' in query
