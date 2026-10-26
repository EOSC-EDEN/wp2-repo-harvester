"""Tests for identifier recognition."""

import pytest

from repo_harvester_server.id_to_iri import detect_re3data_identifier, resolve_identifier


@pytest.mark.parametrize(
    "identifier,scheme,normalized,iri",
    [
        ("10.1594/PANGAEA", "doi", "10.1594/PANGAEA", "https://doi.org/10.1594/PANGAEA"),
        (
            "https://doi.org/10.1594/PANGAEA",
            "doi",
            "10.1594/PANGAEA",
            "https://doi.org/10.1594/PANGAEA",
        ),
        (
            "https://hdl.handle.net/20.500.123/ABC",
            "handle",
            "20.500.123/ABC",
            "https://hdl.handle.net/20.500.123/ABC",
        ),
        (
            "https://orcid.org/0000-0003-1106-8441",
            "orcid",
            "0000-0003-1106-8441",
            "https://orcid.org/0000-0003-1106-8441",
        ),
        ("https://ror.org/03yrm5c26", "ror", "03yrm5c26", "https://ror.org/03yrm5c26"),
        (
            "SAMN12345678",
            "biosample",
            "SAMN12345678",
            "https://www.ebi.ac.uk/ena/data/view/SAMN12345678",
        ),
        (
            "http://example.org/CaseSensitive",
            "url",
            "http://example.org/CaseSensitive",
            "https://example.org/CaseSensitive",
        ),
        (
            "urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd",
            "urn",
            "urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd",
            "urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd",
        ),
        (
            "r3d100010134",
            "re3data",
            "r3d100010134",
            "https://www.re3data.org/repository/r3d100010134",
        ),
        ("9780306406157", "isbn", "978-0-306-40615-7", "urn:isbn:978-0-306-40615-7"),
    ],
)
def test_resolve_identifier(identifier, scheme, normalized, iri):
    resolution = resolve_identifier(identifier)

    assert resolution.original == identifier
    assert resolution.scheme == scheme
    assert resolution.normalized == normalized
    assert resolution.iri == iri


def test_resolve_identifier_honors_preferred_scheme():
    identifier = "https://doi.org/10.1594/PANGAEA"

    resolution = resolve_identifier(identifier, preferred_scheme="URL")

    assert resolution.scheme == "url"
    assert resolution.normalized == identifier
    assert resolution.iri == identifier


def test_resolve_identifier_rejects_unmatched_preferred_scheme():
    with pytest.raises(ValueError, match="not 'orcid'"):
        resolve_identifier("https://doi.org/10.1594/PANGAEA", preferred_scheme="orcid")


def test_resolve_identifier_preserves_original():
    original = "  <https://doi.org/10.1594/PANGAEA>  "

    resolution = resolve_identifier(original, preferred_scheme="DOI")

    assert resolution.original == original
    assert resolution.scheme == "doi"
    assert resolution.normalized == "10.1594/PANGAEA"
    assert resolution.iri == "https://doi.org/10.1594/PANGAEA"


def test_resolve_identifier_rejects_unknown_identifier():
    with pytest.raises(ValueError, match="Could not detect a supported identifier scheme"):
        resolve_identifier("custom-local-id-1234")


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
