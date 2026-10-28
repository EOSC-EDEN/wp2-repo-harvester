"""Tests for mapping harvested values to KB attributes."""

from unittest import mock

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, FOAF

from repo_harvester_server.helper import FUSEKIHelper as fuseki_module
from repo_harvester_server.helper.AttributeMapper import add_attribute_values, apply_kb_attributes, map_attributes
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper

REPO = URIRef("https://example.org/")
ATT = "https://w3id.org/trsp/att.X"
R3D = "http://www.re3data.org/schema/4-0#"


def _graph(*triples):
    g = Graph()
    for triple in triples:
        g.add(triple)
    return g


def _record():
    return {"foaf:primaryTopic": {"@id": str(REPO)}}


def test_merged_pattern_adds_value():
    merged = _graph((REPO, DCTERMS.title, Literal("X")))
    assert map_attributes(merged, REPO, [], [(ATT, "?repository dct:title ?value")]) == {ATT: ["X"]}


def test_raw_pattern_binds_the_main_node():
    main = BNode()
    raw = _graph((URIRef("eden://harvester/raw/re3data/https://example.org/"), FOAF.primaryTopic, main),
                 (main, URIRef(R3D + "pidSystem"), Literal("DOI")))
    assert map_attributes(Graph(), REPO, [raw], [(ATT, "?repository r3d:pidSystem ?value")]) == {ATT: ["DOI"]}


def test_invalid_pattern_is_skipped_with_warning(caplog):
    merged = _graph((REPO, DCTERMS.title, Literal("X")))
    patterns = [("https://w3id.org/trsp/att.BAD", "?repository dct:title ?value }"),
                (ATT, "?repository dct:title ?value")]
    assert map_attributes(merged, REPO, [], patterns) == {ATT: ["X"]}
    assert any(r.levelname == "WARNING" and "att.BAD" in r.getMessage() for r in caplog.records)


def test_blank_node_values_are_skipped():
    merged = _graph((REPO, DCTERMS.publisher, BNode()))
    assert map_attributes(merged, REPO, [], [(ATT, "?repository dct:publisher ?value")]) == {}


def test_typed_literal_becomes_plain_string():
    merged = _graph((REPO, DCTERMS.extent, Literal(3)))
    values = map_attributes(merged, REPO, [], [(ATT, "?repository dct:extent ?value")])
    assert add_attribute_values(_record(), values)["foaf:primaryTopic"][ATT] == ["3"]


def test_duplicate_values_are_written_once():
    licence = URIRef("https://creativecommons.org/licenses/by/4.0/")
    merged = _graph((REPO, DCTERMS.license, licence), (REPO, DCTERMS.rights, licence),
                    (REPO, DCTERMS.rights, Literal(str(licence))))
    patterns = [(ATT, "?repository dct:license ?value"), (ATT, "?repository dct:rights ?value")]
    values = map_attributes(merged, REPO, [], patterns)
    assert add_attribute_values(_record(), values)["foaf:primaryTopic"][ATT] == [{"@id": str(licence)}]


def test_missing_patterns_leave_record_unchanged(caplog):
    fuseki = mock.Mock()
    fuseki.get_source_patterns.return_value = []
    assert apply_kb_attributes(_record(), str(REPO), fuseki) == _record()
    assert any(r.levelname == "WARNING" and "KB source patterns not found" in r.getMessage()
               for r in caplog.records)


def test_raw_graphs_are_selected_by_repository_url():
    with mock.patch.object(fuseki_module, "SPARQLWrapper") as wrapper:
        FUSEKIHelper().get_raw_graphs('https://example.org/"x')
    query = wrapper.return_value.setQuery.call_args.args[0]
    assert 'STRSTARTS(STR(?g), "eden://harvester/raw/")' in query
    assert r'STRENDS(STR(?g), "/https://example.org/\"x")' in query


def test_raw_graphs_read_n_triples_as_utf8():
    # FUSEKI sends N-Triples without a charset, so response.text holds a guessed decoding.
    nt = '<https://example.org/> <http://purl.org/dc/terms/title> "Hava ölçümü" .\n'.encode()
    rows = [{"g": {"value": "eden://harvester/raw/re3data/https://example.org/"}}]
    with mock.patch.object(FUSEKIHelper, "_select", return_value=rows), \
            mock.patch.object(fuseki_module.requests, "get", return_value=mock.Mock(content=nt, text=nt.decode("latin-1"))):
        [graph] = FUSEKIHelper().get_raw_graphs(str(REPO))
    assert (REPO, DCTERMS.title, Literal("Hava ölçümü")) in graph


SNAPSHOT = "eden://kb/snapshots/fidelis-sheet"
HARVESTED = "eden://harvester/re3data/https://example.org/"
ATT_B = "https://w3id.org/trsp/att.B"
TITLE_PATTERN = (ATT, "?repository dct:title ?value")


def _harmonised_record():
    return {"@context": {"dct": "http://purl.org/dc/terms/", "foaf": "http://xmlns.com/foaf/0.1/",
                         "prov": "http://www.w3.org/ns/prov#"},
            "foaf:primaryTopic": {"@id": str(REPO), "dct:title": "X", "prov:hadPrimarySource": [HARVESTED]}}


def _fuseki(snapshot):
    fuseki = mock.Mock()
    fuseki.get_source_patterns.return_value = [TITLE_PATTERN]
    fuseki.get_raw_graphs.return_value = []
    fuseki.get_snapshot_values.return_value = snapshot
    return fuseki


def test_snapshot_values_fill_attributes_the_harvest_left_empty():
    fuseki = _fuseki([(SNAPSHOT, ATT, "From the sheet"), (SNAPSHOT, ATT_B, "Sheet 1"), (SNAPSHOT, ATT_B, "Sheet 2")])
    topic = apply_kb_attributes(_harmonised_record(), str(REPO), fuseki)["foaf:primaryTopic"]
    assert topic[ATT] == ["X"]
    assert topic[ATT_B] == ["Sheet 1", "Sheet 2"]


def test_snapshot_graph_is_recorded_as_a_source():
    used = apply_kb_attributes(_harmonised_record(), str(REPO), _fuseki([(SNAPSHOT, ATT_B, "Sheet")]))
    unused = apply_kb_attributes(_harmonised_record(), str(REPO), _fuseki([(SNAPSHOT, ATT, "Sheet")]))
    assert used["foaf:primaryTopic"]["prov:hadPrimarySource"] == [HARVESTED, SNAPSHOT]
    assert unused["foaf:primaryTopic"]["prov:hadPrimarySource"] == [HARVESTED]


def test_snapshot_query_matches_the_repository_without_case_anchor_or_trailing_slash():
    with mock.patch.object(fuseki_module, "SPARQLWrapper") as wrapper:
        FUSEKIHelper().get_snapshot_values("https://Example.org/portal/#overview")
    query = wrapper.return_value.setQuery.call_args.args[0]
    assert 'STRSTARTS(STR(?g), "eden://kb/snapshots/")' in query
    assert 'LCASE(REPLACE(REPLACE(STR(?repository), "#.*$", ""), "/+$", "")) = "https://example.org/portal"' in query
