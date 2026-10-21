"""Tests for identifier recognition."""

import pytest

from repo_harvester_server.id_to_iri import detect_re3data_identifier


@pytest.mark.parametrize(
    "identifier",
    [
        "https://www.re3data.org/repository/r3d100010137",
        "re3data:r3d100013316",
        "r3d100013316",
    ],
)
def test_detect_re3data_identifier(identifier):
    assert detect_re3data_identifier(identifier) == "re3data"


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "r3d",
        "r3d100013316extra",
        "prefix-r3d100013316",
        "re3data:100013316",
        "https://example.org/repository/r3d100010137",
        "https://www.re3data.org/repository/r3d100010137/extra",
        "r3d１０００１３３１６",
    ],
)
def test_detect_re3data_identifier_rejects_other_values(identifier):
    assert detect_re3data_identifier(identifier) is None
