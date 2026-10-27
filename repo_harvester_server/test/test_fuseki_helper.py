"""Tests for reading graphs back from FUSEKI."""

import json
from unittest import mock

from repo_harvester_server.helper import FUSEKIHelper as fuseki_module
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper

G = "eden://harvester/re3data/https://example.org/"
TOPIC = "http://xmlns.com/foaf/0.1/primaryTopic"


def _repo_graph(response):
    """The graph G as get_repo_graphs returns it when FUSEKI answers with response."""
    with mock.patch.object(fuseki_module, "SPARQLWrapper") as wrapper, \
            mock.patch.object(fuseki_module.requests, "get", return_value=response):
        wrapper.return_value.query.return_value.convert.return_value = {"results": {"bindings": [{"g": {"value": G}}]}}
        return FUSEKIHelper().get_repo_graphs("https://example.org/")[G]


def test_repo_graphs_do_not_depend_on_fuseki_prefixes():
    # FUSEKI after a PUT that replaced its prefixes with none: JSON-LD comes back with full IRIs.
    response = mock.Mock(content=f"<{G}> <{TOPIC}> <https://example.org/> .\n".encode())
    response.json.return_value = {"@graph": [{"@id": G, TOPIC: {"@id": "https://example.org/"}}]}
    graph = _repo_graph(response)
    assert any(node.get("foaf:primaryTopic") == {"@id": "https://example.org/"}
               for node in graph.get("@graph", [graph]))


def test_repo_graphs_read_n_triples_as_utf8():
    # FUSEKI sends N-Triples without a charset, so response.text holds a guessed decoding.
    nt = '<https://example.org/> <http://purl.org/dc/terms/title> "Hava ölçümü" .\n'.encode()
    graph = _repo_graph(mock.Mock(content=nt, text=nt.decode("latin-1")))
    assert "Hava ölçümü" in json.dumps(graph, ensure_ascii=False)
