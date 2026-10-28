"""Tests for re-harmonising every harvested repository."""

from harmonize_all import repository_urls


def test_repository_urls_come_from_source_graphs_only():
    assert repository_urls([
        "eden://harvester/re3data/https://a.org/",
        "eden://harvester/embedded_jsonld/https://a.org/",
        "eden://harvester/harmonized/https://a.org/",
        "eden://harvester/raw/re3data/https://a.org/",
        "eden://kb/definitions",
        "eden://validator/run/1",
    ]) == ["https://a.org/"]
