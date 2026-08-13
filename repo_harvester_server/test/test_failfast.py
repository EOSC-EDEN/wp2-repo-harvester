"""
Tests for honest reporting of harvest runs.

Covers the startup auth probe (FUSEKIHelper.check_connection), the
empty-store-is-normal contract of get_repo_graphs, the per-stage flags
returned by harvest_all.harvest_repository, and the per-stage counts in
the _harvest_summary.json dict.
"""
import datetime
from unittest import mock

import pytest
import requests

from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper, FusekiAuthError

import harvest_all


def _response(status_code, json_body=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


@pytest.fixture
def fuseki_credentials(monkeypatch):
    monkeypatch.setenv('FUSEKI_USERNAME', 'fuseki')
    monkeypatch.setenv('FUSEKI_PASSWORD', 'secret')


class TestCheckConnection:

    def test_401_raises_auth_error(self, fuseki_credentials):
        with mock.patch(
            'repo_harvester_server.helper.FUSEKIHelper.requests.get',
            return_value=_response(401),
        ):
            with pytest.raises(FusekiAuthError) as exc:
                FUSEKIHelper().check_connection()
        # the message must name what to fix
        assert 'FUSEKI_USERNAME' in str(exc.value)
        assert '401' in str(exc.value)

    def test_200_returns_cleanly(self, fuseki_credentials):
        with mock.patch(
            'repo_harvester_server.helper.FUSEKIHelper.requests.get',
            return_value=_response(200, {'boolean': True}),
        ):
            FUSEKIHelper().check_connection()  # must not raise

    def test_missing_credentials_raise_before_any_request(self, monkeypatch):
        monkeypatch.delenv('FUSEKI_USERNAME', raising=False)
        monkeypatch.delenv('FUSEKI_PASSWORD', raising=False)
        with mock.patch(
            'repo_harvester_server.helper.FUSEKIHelper.requests.get'
        ) as get:
            with pytest.raises(FusekiAuthError) as exc:
                FUSEKIHelper().check_connection()
        get.assert_not_called()
        assert 'FUSEKI_USERNAME' in str(exc.value)

    def test_unreachable_server_raises_auth_error(self, fuseki_credentials):
        with mock.patch(
            'repo_harvester_server.helper.FUSEKIHelper.requests.get',
            side_effect=requests.exceptions.ConnectionError('refused'),
        ):
            with pytest.raises(FusekiAuthError):
                FUSEKIHelper().check_connection()


class TestEmptyStoreIsNormal:
    """An empty store on a first run must stay a normal, non-error outcome."""

    def test_get_repo_graphs_empty_store_returns_empty_dict(self, fuseki_credentials):
        with mock.patch(
            'repo_harvester_server.helper.FUSEKIHelper.SPARQLWrapper'
        ) as sparql_cls:
            sparql = sparql_cls.return_value
            sparql.query.return_value.convert.return_value = {
                'results': {'bindings': []}
            }
            result = FUSEKIHelper().get_repo_graphs('https://example.org/')
        assert result == {}


class TestPerStageFlags:

    def _harvester(self, records, harmonized_ok, persisted_ok):
        harvester = mock.Mock()
        harvester.harvest.return_value = records
        harvester.catalog_url = 'https://example.org/'
        harvester.harmonized_ok = harmonized_ok
        harvester.persisted_ok = persisted_ok
        harvester.degraded_sources = []
        return harvester

    def test_harvested_but_not_harmonized_is_not_an_error(self):
        records = [{'foaf:primaryTopic': {'@id': 'https://example.org/'}}]
        with mock.patch(
            'harvest_all.RepositoryHarvester',
            return_value=self._harvester(records, False, False),
        ):
            result, stages = harvest_all.harvest_repository(
                'https://example.org/', 'Example'
            )
        assert stages == {
            'harvested': True, 'harmonized': False, 'persisted': False,
            'degraded_sources': [],
        }
        assert result['repoURI'] == 'https://example.org/'

    def test_fully_persisted_repo(self):
        records = [{'foaf:primaryTopic': {'@id': 'https://example.org/'}}]
        with mock.patch(
            'harvest_all.RepositoryHarvester',
            return_value=self._harvester(records, True, True),
        ):
            _, stages = harvest_all.harvest_repository(
                'https://example.org/', 'Example'
            )
        assert stages == {
            'harvested': True, 'harmonized': True, 'persisted': True,
            'degraded_sources': [],
        }


class TestSummaryJson:

    def test_summary_contains_per_stage_flags_and_counts(self):
        results = {
            'success': [
                {'name': 'A', 'url': 'https://a.example/', 'file': 'output/A.json',
                 'services': 2, 'harvested': True, 'harmonized': True, 'persisted': True},
                {'name': 'B', 'url': 'https://b.example/', 'file': 'output/B.json',
                 'services': 0, 'harvested': True, 'harmonized': False, 'persisted': False},
            ],
            'failed': [
                {'name': 'C', 'url': 'https://c.example/', 'error': 'boom'},
            ],
            'skipped': [],
        }
        start = datetime.datetime(2026, 8, 10, 12, 0, 0)
        summary = harvest_all.build_summary(
            3, results, start, datetime.timedelta(seconds=42)
        )
        assert summary['total'] == 3
        assert summary['success_count'] == 2
        assert summary['failed_count'] == 1
        assert summary['harmonized_count'] == 1
        assert summary['persisted_count'] == 1
        assert summary['success'][0]['harmonized'] is True
        assert summary['success'][1]['harmonized'] is False
        assert summary['success'][1]['persisted'] is False
