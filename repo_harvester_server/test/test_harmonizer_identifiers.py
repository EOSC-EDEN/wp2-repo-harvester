from unittest.mock import MagicMock, patch
import pytest

from repo_harvester_server.helper.RepositoryHarmonizer import (
    RepositoryHarmonizer,
    _normalize_identifiers,
)


def test_normalize_identifiers_empty():
    assert _normalize_identifiers([]) == []
    assert _normalize_identifiers(None) == []
    assert _normalize_identifiers(["", "   ", None]) == []


def test_normalize_identifiers_deduplication():
    raw_identifiers = [
        "10.1594/PANGAEA",
        "https://doi.org/10.1594/PANGAEA",
        "doi:10.1594/PANGAEA",
        "r3d100010134",
        "SAMN12345678",
        "https://www.ebi.ac.uk/ena/data/view/samn12345678",
        "https://www.re3data.org/repository/r3d100010134",
        "https://pangaea.de/",
        "urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd",
    ]
    normalized = _normalize_identifiers(raw_identifiers)
    assert set(normalized) == {
        "https://doi.org/10.1594/pangaea",
        "https://www.re3data.org/repository/r3d100010134",
        "https://pangaea.de/",
        "urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd",
        "https://www.ebi.ac.uk/ena/data/view/samn12345678",
    }


def test_normalize_identifiers_fallback():
    raw_identifiers = [
        "custom-local-id-1234",
        "<https://doi.org/10.1594/PANGAEA>",
    ]
    normalized = _normalize_identifiers(raw_identifiers)
    assert set(normalized) == {
        "custom-local-id-1234",
        "https://doi.org/10.1594/pangaea",
    }


def test_harmonize_normalizes_identifiers():
    repouri = "https://pangaea.de/"
    sample_graph_landing = {
        "@id": "eden://harvester/landing_page/https://pangaea.de/",
        "primaryTopic": {
            "@id": repouri,
            "@type": "DataCatalog",
            "name": "PANGAEA",
            "identifier": [
                "10.1594/PANGAEA",
                "https://pangaea.de/",
            ],
        },
    }
    sample_graph_re3data = {
        "@id": "eden://harvester/re3data/https://pangaea.de/",
        "primaryTopic": {
            "@id": repouri,
            "@type": "DataCatalog",
            "name": "PANGAEA",
            "identifier": [
                "https://doi.org/10.1594/PANGAEA",
                "r3d100010134",
                "https://www.re3data.org/repository/r3d100010134",
            ],
        },
    }

    harmonizer = RepositoryHarmonizer(repouri)
    harmonizer.fuseki = MagicMock()
    harmonizer.fuseki.get_repo_graphs.return_value = {
        "eden://harvester/landing_page/https://pangaea.de/": sample_graph_landing,
        "eden://harvester/re3data/https://pangaea.de/": sample_graph_re3data,
    }
    harmonizer.fuseki.save.return_value = 10

    with patch.object(harmonizer, "enrich_services_with_validation"):
        result = harmonizer.harmonize()

    assert result is not False
    primary_topic = result.get("foaf:primaryTopic", {})
    dct_identifiers = primary_topic.get("dct:identifier")
    assert isinstance(dct_identifiers, list)
    assert set(dct_identifiers) == {
        "https://doi.org/10.1594/pangaea",
        "https://www.re3data.org/repository/r3d100010134",
        "https://pangaea.de/",
    }
