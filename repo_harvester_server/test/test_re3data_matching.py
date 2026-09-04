"""Tests for choosing the right re3data repository."""

from unittest import mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester

RE3DATA_NS = "http://www.re3data.org/schema/2-2"


def _response(content):
    response = mock.Mock()
    response.status_code = 200
    response.content = content
    response.headers = {}
    response.text = content.decode("utf-8", "replace")
    response.raise_for_status.return_value = None
    return response


def _search_xml(*repositories):
    entries = "".join(
        f"<repository><id>{repo_id}</id><name>{name}</name></repository>"
        for repo_id, name in repositories
    )
    return f"<list>{entries}</list>".encode()


def _record_xml(name, repository_url):
    return (
        f'<r3d:repository xmlns:r3d="{RE3DATA_NS}">'
        f"<r3d:repositoryName>{name}</r3d:repositoryName>"
        f"<r3d:repositoryURL>{repository_url}</r3d:repositoryURL>"
        "</r3d:repository>"
    ).encode()


def _query_from_request(url, kwargs):
    if kwargs.get("params"):
        return kwargs["params"].get("query")
    return parse_qs(urlsplit(url).query).get("query", [None])[0]


def _registry_api(search_results, records):
    """Return fake re3data replies for tests."""

    def request(_method, url, **kwargs):
        if urlsplit(url).path.endswith("/repositories"):
            query = _query_from_request(url, kwargs)
            return _response(_search_xml(*search_results.get(query, ())))

        repo_id = urlsplit(url).path.rsplit("/", 1)[-1]
        name, repository_url = records[repo_id]
        return _response(_record_xml(name, repository_url))

    return request


@pytest.mark.parametrize(
    ("submitted_url", "expected_title", "search_records", "detail_records"),
    [
        (
            "https://www.ebi.ac.uk/biosamples/",
            "BioSamples",
            (("r3d-pride", "PRIDE"), ("r3d-biosamples", "BioSamples")),
            {
                "r3d-pride": ("PRIDE", "https://www.ebi.ac.uk/pride/"),
                "r3d-biosamples": (
                    "BioSamples",
                    "https://www.ebi.ac.uk/biosamples/",
                ),
            },
        ),
        (
            "https://dataverse.no/dataverse/trolling",
            "TROLLing",
            (("r3d-dataverse", "DataverseNO"), ("r3d-trolling", "TROLLing")),
            {
                "r3d-dataverse": ("DataverseNO", "https://dataverse.no/"),
                "r3d-trolling": (
                    "TROLLing",
                    "https://dataverse.no/dataverse/trolling",
                ),
            },
        ),
        (
            "https://www.uniprot.org/",
            "UniProt",
            (("r3d-uniprotkb", "UniProtKB"), ("r3d-uniprot", "UniProt")),
            {
                "r3d-uniprotkb": (
                    "UniProtKB",
                    "https://www.uniprot.org/uniprotkb/",
                ),
                "r3d-uniprot": ("UniProt", "https://www.uniprot.org/"),
            },
        ),
    ],
)
def test_exact_repository_url_wins_over_first_shared_hostname_result(
    submitted_url, expected_title, search_records, detail_records
):
    """A matching path must win over the first result from the same host."""
    hostname = urlsplit(submitted_url).hostname
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: search_records,
            hostname: search_records,
        },
        detail_records,
    )

    result = harvester.harvest(submitted_url)

    assert result["title"] == expected_title


def test_multiple_hostname_matches_without_identifying_evidence_are_ambiguous():
    """Do not choose when several records match only by hostname."""
    submitted_url = "https://shared.example.org/unknown"
    search_records = (("r3d-one", "One"), ("r3d-two", "Two"))
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: search_records,
            "shared.example.org": search_records,
        },
        {
            "r3d-one": ("One", "https://shared.example.org/one"),
            "r3d-two": ("Two", "https://shared.example.org/two"),
        },
    )

    assert harvester.harvest(submitted_url) is None


def test_one_canonical_hostname_candidate_remains_a_valid_match():
    """Keep one clear match when one hostname adds a single prefix."""
    submitted_url = "https://about.coscine.de/"
    search_records = (("r3d-coscine", "Coscine"),)
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: search_records,
            "about.coscine.de": search_records,
        },
        {"r3d-coscine": ("Coscine", "https://www.coscine.de/")},
    )

    result = harvester.harvest(submitted_url)

    assert result["title"] == "Coscine"


def test_repository_name_disambiguates_records_with_the_same_exact_url():
    submitted_url = "https://shared.example.org/"
    search_records = (("r3d-one", "Repository One"), ("r3d-two", "Repository Two"))
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {submitted_url: search_records},
        {
            "r3d-one": ("Repository One", submitted_url),
            "r3d-two": ("Repository Two", submitted_url),
        },
    )

    result = harvester.harvest(submitted_url, "Repository Two")

    assert result["title"] == "Repository Two"


def test_repository_name_finds_a_record_after_a_redirect_changes_its_host():
    submitted_url = "https://dans.knaw.nl/en/data-stations/life-sciences/"
    redirected_url = "https://lifesciences.datastations.nl/"
    repository_name = "DANS - Life Sciences"
    name_results = (
        ("r3d-physical", "DANS Data Station Physical and Technical Sciences"),
        ("r3d-life", "DANS Data Station Life Sciences"),
    )
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (),
            redirected_url: (),
            "dans.knaw.nl": (),
            "lifesciences.datastations.nl": (),
            repository_name: name_results,
        },
        {
            "r3d-physical": (
                "DANS Data Station Physical and Technical Sciences",
                "https://phys-techsciences.datastations.nl/",
            ),
            "r3d-life": (
                "DANS Data Station Life Sciences",
                "https://lifesciences.datastations.nl/",
            ),
        },
    )

    result = harvester.harvest(
        f"{submitted_url}|{redirected_url}", repository_name
    )

    assert result["title"] == "DANS Data Station Life Sciences"


def test_related_landing_page_path_breaks_an_acronym_name_tie():
    submitted_url = "https://www.gesis.org/en/data-services"
    repository_name = "GESIS - Leibniz Institute for the Social Sciences"
    search_records = (
        ("r3d-search", "GESIS Search"),
        ("r3d-archive", "GESIS Data Archive"),
    )
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: search_records,
            repository_name: search_records,
        },
        {
            "r3d-search": ("GESIS Search", "https://www.gesis.org/en/search"),
            "r3d-archive": (
                "GESIS Data Archive",
                "https://www.gesis.org/en/data-services/share-data",
            ),
        },
    )

    result = harvester.harvest(submitted_url, repository_name)

    assert result["title"] == "GESIS Data Archive"


def test_name_search_does_not_accept_exact_name_on_an_unrelated_url():
    submitted_url = "https://expected.example.org/"
    repository_name = "Expected Repository"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (),
            "expected.example.org": (),
            repository_name: (("r3d-other", repository_name),),
        },
        {
            "r3d-other": (
                repository_name,
                "https://unrelated.example.net/",
            ),
        },
    )

    assert harvester.harvest(submitted_url, repository_name) is None


def test_name_search_result_needs_a_name_match_on_the_same_host():
    submitted_url = "https://shared.example.org/expected"
    repository_name = "Expected Repository"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (),
            "shared.example.org": (),
            repository_name: (("r3d-other", "Different Service"),),
        },
        {
            "r3d-other": (
                "Different Service",
                "https://shared.example.org/other",
            ),
        },
    )

    assert harvester.harvest(submitted_url, repository_name) is None


def test_hostname_search_expands_an_incomplete_full_url_result():
    submitted_url = "https://shared.example.org/unknown"
    hostname = "shared.example.org"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (("r3d-one", "One"),),
            hostname: (("r3d-one", "One"), ("r3d-two", "Two")),
        },
        {
            "r3d-one": ("One", "https://shared.example.org/one"),
            "r3d-two": ("Two", "https://shared.example.org/two"),
        },
    )

    assert harvester.harvest(submitted_url) is None


def test_ambiguous_name_search_logs_candidate_ids(caplog):
    submitted_url = "https://retired.example.org/repository"
    repository_name = "Shared Repository"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (),
            "retired.example.org": (),
            repository_name: (
                ("r3d-first", repository_name),
                ("r3d-second", repository_name),
            ),
        },
        {
            "r3d-first": (repository_name, "https://first.example.net/"),
            "r3d-second": (repository_name, "https://second.example.net/"),
        },
    )

    with caplog.at_level("WARNING", logger="Re3DataHarvester"):
        assert harvester.harvest(submitted_url, repository_name) is None

    assert "r3d-first" in caplog.text
    assert "r3d-second" in caplog.text


def test_name_search_cannot_hide_compatible_candidate_ambiguity(caplog):
    submitted_url = "https://shared.example.org/unknown"
    repository_name = "Target Repository"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (("r3d-other", "Different Service"),),
            "shared.example.org": (("r3d-other", "Different Service"),),
            repository_name: (
                ("r3d-first", repository_name),
                ("r3d-second", repository_name),
            ),
        },
        {
            "r3d-other": (
                "Different Service",
                "https://shared.example.org/other",
            ),
            "r3d-first": (
                repository_name,
                "https://shared.example.org/first",
            ),
            "r3d-second": (
                repository_name,
                "https://shared.example.org/second",
            ),
        },
    )

    with caplog.at_level("WARNING", logger="Re3DataHarvester"):
        assert harvester.harvest(submitted_url, repository_name) is None

    assert "r3d-first" in caplog.text
    assert "r3d-second" in caplog.text


def test_malformed_candidate_port_is_skipped(caplog):
    submitted_url = "https://example.org/repository"
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (
                ("r3d-invalid", "Invalid"),
                ("r3d-valid", "Valid"),
            ),
        },
        {
            "r3d-invalid": (
                "Invalid",
                "https://example.org:99999/repository",
            ),
            "r3d-valid": ("Valid", submitted_url),
        },
    )

    with caplog.at_level("WARNING", logger="Re3DataHarvester"):
        result = harvester.harvest(submitted_url)

    assert result["title"] == "Valid"
    assert "invalid port" in caplog.text.lower()


def test_url_normalization_ignores_only_non_identifying_differences():
    harvester = Re3DataHarvester()

    assert harvester._normalize_url(
        "HTTPS://WWW.Example.ORG/path/#section"
    ) == harvester._normalize_url("http://example.org/path")
    assert harvester._normalize_url(
        "http://example.org:80/path"
    ) == harvester._normalize_url("https://example.org/path")
    assert harvester._normalize_url(
        "https://example.org:8443/path"
    ) != harvester._normalize_url("https://example.org:9443/path")


def test_exact_url_found_by_name_search_still_has_highest_priority():
    submitted_url = "https://expected.example.org/repository"
    repository_name = "Current Repository Name"
    name_results = (
        ("r3d-exact", "Historical Registry Name"),
        ("r3d-name", "Current Repository Name"),
    )
    harvester = Re3DataHarvester()
    harvester.session = mock.Mock()
    harvester.session.request.side_effect = _registry_api(
        {
            submitted_url: (),
            "expected.example.org": (),
            repository_name: name_results,
        },
        {
            "r3d-exact": ("Historical Registry Name", submitted_url),
            "r3d-name": (
                "Current Repository Name",
                "https://different.example.net/",
            ),
        },
    )

    result = harvester.harvest(submitted_url, repository_name)

    assert result["title"] == "Historical Registry Name"


def test_repository_harvester_passes_the_known_name_to_re3data(monkeypatch):
    monkeypatch.setenv("FAIRSHARING_USERNAME", "user")
    monkeypatch.setenv("FAIRSHARING_PASSWORD", "secret")
    monkeypatch.setenv("FUSEKI_USERNAME", "fuseki")
    monkeypatch.setenv("FUSEKI_PASSWORD", "secret")
    re3data = mock.Mock()
    re3data.harvest.return_value = None
    fairsharing = mock.Mock()
    fairsharing.harvest.return_value = None

    # The landing page must not be fetched: a redirect would append a second
    # entry to catalog_ids and change what re3data is asked. Injecting a
    # failing session is how the harvester takes an offline stand-in now -
    # patching module-level requests.get no longer intercepts anything, since
    # every outbound fetch goes through the guarded session.
    session = mock.Mock()
    session.get.side_effect = requests.exceptions.ConnectionError("offline test")

    harvester = RepositoryHarvester(
        "https://dans.knaw.nl/en/data-stations/life-sciences/",
        re3data_harvester=re3data,
        fairsharing_harvester=fairsharing,
        repository_name="DANS - Life Sciences",
        session=session,
    )

    harvester.harvest_registry_metadata()

    re3data.harvest.assert_called_once_with(
        "https://dans.knaw.nl/en/data-stations/life-sciences/",
        "DANS - Life Sciences",
    )
