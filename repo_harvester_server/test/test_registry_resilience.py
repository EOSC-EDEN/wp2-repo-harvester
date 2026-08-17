"""Tests for honest reporting when an external registry cannot be consulted.

A rate-limited registry must degrade the repository (recording which source is
missing) without failing it and without stopping the batch.
"""
import datetime
from unittest import mock

import pytest
import requests
import requests as _requests

import harvest_all
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.RegistryHTTP import RegistryUnavailableError
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester
from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester


@pytest.fixture
def harvester_credentials(monkeypatch):
    monkeypatch.setenv('FAIRSHARING_USERNAME', 'user')
    monkeypatch.setenv('FAIRSHARING_PASSWORD', 'secret')
    monkeypatch.setenv('FUSEKI_USERNAME', 'fuseki')
    monkeypatch.setenv('FUSEKI_PASSWORD', 'secret')


def _repo_harvester(**kwargs):
    """Build a RepositoryHarvester without touching the network in __init__.

    The side effect must be a requests exception, not a bare Exception:
    __init__ deliberately catches only RequestException, and widening that
    catch to satisfy a test would swallow real programming errors.
    """
    session = mock.Mock()
    session.get.side_effect = requests.exceptions.ConnectionError('no network in tests')
    kwargs.setdefault('session', session)
    return RepositoryHarvester('https://example.org/', **kwargs)


class TestDegradedSources:

    def test_starts_with_no_degraded_sources(self, harvester_credentials):
        harvester = _repo_harvester()
        assert harvester.degraded_sources == []

    def test_rate_limited_fairsharing_is_recorded_not_raised(self, harvester_credentials):
        re3data = mock.Mock()
        re3data.harvest.return_value = None
        fairsharing = mock.Mock()
        fairsharing.harvest.side_effect = RegistryUnavailableError(
            'fairsharing', 'rate limited (HTTP 429)'
        )
        harvester = _repo_harvester(
            re3data_harvester=re3data, fairsharing_harvester=fairsharing
        )

        harvester.harvest_registry_metadata()  # must not raise

        assert harvester.degraded_sources == ['fairsharing']

    def test_rate_limited_re3data_is_recorded(self, harvester_credentials):
        re3data = mock.Mock()
        re3data.harvest.side_effect = RegistryUnavailableError(
            're3data', 'rate limited (HTTP 429)'
        )
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = None
        harvester = _repo_harvester(
            re3data_harvester=re3data, fairsharing_harvester=fairsharing
        )

        harvester.harvest_registry_metadata()

        assert harvester.degraded_sources == ['re3data']

    def test_genuine_miss_is_not_degraded(self, harvester_credentials):
        """Registry answered, has no such record: a normal outcome, not a degradation."""
        re3data = mock.Mock()
        re3data.harvest.return_value = None
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = None
        harvester = _repo_harvester(
            re3data_harvester=re3data, fairsharing_harvester=fairsharing
        )

        harvester.harvest_registry_metadata()

        assert harvester.degraded_sources == []

    def test_degraded_registry_is_not_retried_for_the_same_repo(self, harvester_credentials):
        """Once re3data is known unavailable, the bridge call must not hit it again."""
        re3data = mock.Mock()
        re3data.harvest.side_effect = RegistryUnavailableError('re3data', 'rate limited')
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = {'title': 'Example', 'identifier': ['r3d100000001']}
        harvester = _repo_harvester(
            re3data_harvester=re3data, fairsharing_harvester=fairsharing
        )

        harvester.harvest_registry_metadata()

        re3data.harvest_by_id.assert_not_called()
        re3data.harvest_by_name.assert_not_called()
        assert harvester.degraded_sources == ['re3data']

    def test_injected_harvesters_are_used(self, harvester_credentials):
        """A batch shares one FAIRsharing session; the class must not build its own."""
        re3data = mock.Mock()
        re3data.harvest.return_value = None
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = None
        harvester = _repo_harvester(
            re3data_harvester=re3data, fairsharing_harvester=fairsharing
        )

        with mock.patch(
            'repo_harvester_server.helper.RepositoryHarvester.FAIRsharingHarvester'
        ) as fs_cls:
            harvester.harvest_registry_metadata()
        fs_cls.assert_not_called()
        fairsharing.harvest.assert_called_once()


def _fs_response(status_code, json_body=None, headers=None, text=''):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = headers if headers is not None else {}
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    resp.raise_for_status.return_value = None
    return resp


def _authenticated_harvester(monkeypatch):
    """A FAIRsharingHarvester with a token, without a network sign-in."""
    monkeypatch.setenv('FAIRSHARING_USERNAME', 'user')
    monkeypatch.setenv('FAIRSHARING_PASSWORD', 'secret')
    with mock.patch.object(FAIRsharingHarvester, '_authenticate', autospec=True):
        harvester = FAIRsharingHarvester()
    harvester.jwt_token = 'token-1'
    return harvester


class TestFAIRsharingRateLimiting:

    def test_persistent_429_raises_instead_of_reporting_no_records(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(429) for _ in range(4)]

        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError) as exc:
                harvester.harvest('https://data.example.org/')

        assert exc.value.registry == 'fairsharing'
        assert '429' in str(exc.value)

    def test_429_does_not_trigger_the_second_search_strategy(self, monkeypatch):
        """Strategy 2 while rate-limited is a doomed extra request."""
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(429) for _ in range(4)]

        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError):
                harvester.harvest('https://data.example.org/')

        # 1 initial + 3 retries for strategy 1, and nothing more.
        assert harvester.session.request.call_count == 4

    def test_429_then_success_still_returns_metadata(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        body = {'data': [{
            'id': '1',
            'type': 'fairsharing_records',
            'attributes': {
                # record_type is required by FAIRSHARING_QUERY's join() call
                # (JMESPATHQueries.py); every real FAIRsharing record has it.
                'record_type': 'repository',
                'metadata': {
                    'name': 'Example', 'homepage': 'https://data.example.org/',
                    'status': 'ready',
                },
            },
        }]}
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(429), _fs_response(200, body)]

        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            result = harvester.harvest('https://data.example.org/')

        assert result is not None
        assert harvester.session.request.call_count == 2

    def test_genuine_miss_returns_none(self, monkeypatch):
        """An empty result set is not a degradation."""
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _fs_response(200, {'data': []})

        assert harvester.harvest('https://data.example.org/') is None

    def test_unauthenticated_harvest_raises(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.jwt_token = None

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest('https://data.example.org/')
        assert exc.value.registry == 'fairsharing'

    def test_rate_limited_signin_leaves_token_unset_without_raising(self, monkeypatch):
        """A 429 on sign-in must not kill a batch at construction time."""
        monkeypatch.setenv('FAIRSHARING_USERNAME', 'user')
        monkeypatch.setenv('FAIRSHARING_PASSWORD', 'secret')
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ), mock.patch(
            'repo_harvester_server.helper.FAIRsharingHarvester.requests.Session'
        ) as session_cls:
            session_cls.return_value.request.side_effect = [
                _fs_response(429) for _ in range(4)
            ]
            harvester = FAIRsharingHarvester()  # must not raise
        assert harvester.jwt_token is None


class TestFAIRsharingSessionReuse:

    def test_expired_token_triggers_one_reauth_and_retry(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        body = {'data': [{
            'id': '1',
            'type': 'fairsharing_records',
            'attributes': {
                # record_type is required by FAIRSHARING_QUERY's join() call
                # (JMESPATHQueries.py); every real FAIRsharing record has it.
                'record_type': 'repository',
                'metadata': {
                    'name': 'Example', 'homepage': 'https://data.example.org/',
                    'status': 'ready',
                },
            },
        }]}
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(401), _fs_response(200, body)]

        def _reauth(self_):
            self_.jwt_token = 'token-2'

        with mock.patch.object(
            FAIRsharingHarvester, '_authenticate', autospec=True, side_effect=_reauth
        ) as auth:
            result = harvester.harvest('https://data.example.org/')

        assert result is not None
        assert auth.call_count == 1
        assert harvester.session.request.call_count == 2

    def test_second_401_raises_rather_than_looping(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(401), _fs_response(401)]

        def _reauth(self_):
            self_.jwt_token = 'token-2'

        with mock.patch.object(
            FAIRsharingHarvester, '_authenticate', autospec=True, side_effect=_reauth
        ):
            with pytest.raises(RegistryUnavailableError) as exc:
                harvester.harvest('https://data.example.org/')

        assert '401' in str(exc.value)
        assert harvester.session.request.call_count == 2

    def test_failed_reauth_raises(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_fs_response(401)]

        def _reauth(self_):
            self_.jwt_token = None

        with mock.patch.object(
            FAIRsharingHarvester, '_authenticate', autospec=True, side_effect=_reauth
        ):
            with pytest.raises(RegistryUnavailableError):
                harvester.harvest('https://data.example.org/')

    def test_many_harvests_sign_in_once(self, monkeypatch):
        """The whole point: a shared harvester must not re-authenticate per repo."""
        monkeypatch.setenv('FAIRSHARING_USERNAME', 'user')
        monkeypatch.setenv('FAIRSHARING_PASSWORD', 'secret')
        with mock.patch.object(
            FAIRsharingHarvester, '_authenticate', autospec=True
        ) as auth:
            harvester = FAIRsharingHarvester()
            harvester.jwt_token = 'token-1'
            harvester.session = mock.Mock()
            harvester.session.request.return_value = _fs_response(200, {'data': []})
            for i in range(5):
                harvester.harvest(f'https://repo{i}.example.org/')
        assert auth.call_count == 1


_SEARCH_XML = b'<list><repository><id>r3d100000001</id><name>Example</name></repository></list>'
_EMPTY_XML = b'<list></list>'


def _xml_response(status_code, content=b'<list></list>', headers=None):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = headers if headers is not None else {}
    resp.text = content.decode('utf-8', 'replace')
    resp.raise_for_status.return_value = None
    return resp


class TestRe3DataHonesty:

    def test_persistent_429_raises(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [_xml_response(429) for _ in range(4)]

        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError) as exc:
                harvester.harvest('https://data.example.org/')
        assert exc.value.registry == 're3data'

    def test_connection_error_raises_instead_of_silent_none(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = _requests.exceptions.ConnectionError('refused')

        with pytest.raises(RegistryUnavailableError):
            harvester.harvest('https://data.example.org/')

    def test_no_matching_entry_still_returns_none(self):
        """re3data answered and has nothing: a normal miss, not a degradation."""
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _xml_response(200, _EMPTY_XML)

        assert harvester.harvest('https://data.example.org/') is None

    def test_uses_one_session_for_search_and_record_fetch(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.side_effect = [
            _xml_response(200, _SEARCH_XML),
            _xml_response(200, _EMPTY_XML),
        ]

        harvester.harvest('https://data.example.org/')

        assert harvester.session.request.call_count == 2


class TestHarvestAllDegradedReporting:

    def _harvester(self, records, degraded):
        harvester = mock.Mock()
        harvester.harvest.return_value = records
        harvester.catalog_url = 'https://example.org/'
        harvester.harmonized_ok = True
        harvester.persisted_ok = True
        harvester.degraded_sources = degraded
        return harvester

    def test_stages_carry_degraded_sources(self):
        records = [{'foaf:primaryTopic': {'@id': 'https://example.org/'}}]
        with mock.patch(
            'harvest_all.RepositoryHarvester',
            return_value=self._harvester(records, ['fairsharing']),
        ):
            _, stages = harvest_all.harvest_repository('https://example.org/', 'Example')
        assert stages['degraded_sources'] == ['fairsharing']
        assert stages['harvested'] is True

    def test_clean_repo_has_no_degraded_sources(self):
        records = [{'foaf:primaryTopic': {'@id': 'https://example.org/'}}]
        with mock.patch(
            'harvest_all.RepositoryHarvester',
            return_value=self._harvester(records, []),
        ):
            _, stages = harvest_all.harvest_repository('https://example.org/', 'Example')
        assert stages['degraded_sources'] == []

    def test_shared_harvesters_are_passed_through(self):
        records = [{'foaf:primaryTopic': {'@id': 'https://example.org/'}}]
        re3data = mock.Mock()
        fairsharing = mock.Mock()
        with mock.patch(
            'harvest_all.RepositoryHarvester',
            return_value=self._harvester(records, []),
        ) as cls:
            harvest_all.harvest_repository(
                'https://example.org/', 'Example',
                re3data_harvester=re3data, fairsharing_harvester=fairsharing,
            )
        _, kwargs = cls.call_args
        assert kwargs['re3data_harvester'] is re3data
        assert kwargs['fairsharing_harvester'] is fairsharing

    def test_summary_counts_and_names_degraded_repos(self):
        results = {
            'success': [
                {'name': 'A', 'url': 'https://a.example/', 'file': 'output/A.json',
                 'services': 2, 'harvested': True, 'harmonized': True,
                 'persisted': True, 'degraded_sources': []},
                {'name': 'B', 'url': 'https://b.example/', 'file': 'output/B.json',
                 'services': 1, 'harvested': True, 'harmonized': True,
                 'persisted': True, 'degraded_sources': ['fairsharing']},
            ],
            'failed': [],
            'skipped': [],
        }
        summary = harvest_all.build_summary(
            2, results, datetime.datetime(2026, 8, 11, 12, 0, 0),
            datetime.timedelta(seconds=10),
        )
        assert summary['degraded_count'] == 1
        assert summary['success'][1]['degraded_sources'] == ['fairsharing']
        assert summary['success'][0]['degraded_sources'] == []


def _fs_error_response(status_code):
    """A FAIRsharing response whose raise_for_status raises, like a real 4xx/5xx."""
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = {}
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Server Error"
    )
    return resp


class TestFAIRsharingSearchResponseHonesty:
    """A search response FAIRsharing can't be trusted must degrade, not miss."""

    def test_5xx_search_response_raises_instead_of_reporting_no_records(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _fs_error_response(503)

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest('https://data.example.org/')

        assert exc.value.registry == 'fairsharing'

    def test_invalid_json_body_raises_registry_unavailable(self, monkeypatch):
        """A 200 with an unparsable body (e.g. an HTML error page from a proxy)
        must not escape as requests.exceptions.JSONDecodeError: that reaches
        RepositoryHarvester._try_registry uncaught and fails the whole repo,
        discarding its already-harvested self-hosted metadata."""
        harvester = _authenticated_harvester(monkeypatch)
        resp = mock.Mock()
        resp.status_code = 200
        resp.headers = {}
        resp.raise_for_status.return_value = None
        resp.json.side_effect = requests.exceptions.JSONDecodeError(
            'Expecting value', '<html>error page</html>', 0
        )
        harvester.session = mock.Mock()
        harvester.session.request.return_value = resp

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest('https://data.example.org/')

        assert exc.value.registry == 'fairsharing'


class TestFAIRsharingParseFailureIsAMiss:

    def test_record_missing_record_type_returns_none_not_unbound_local_error(self, monkeypatch):
        """JMESPATHQueries.py's join() call raises JMESPathTypeError when a
        record lacks 'record_type'. _parse_search_results must not fall
        through to `metadata` unassigned (UnboundLocalError), which would
        escape _try_registry and fail the repository outright."""
        harvester = _authenticated_harvester(monkeypatch)
        records = [{
            'id': '1',
            'type': 'fairsharing_records',
            'attributes': {
                # record_type deliberately absent.
                'metadata': {
                    'name': 'Example', 'homepage': 'https://data.example.org/',
                    'status': 'ready',
                },
            },
        }]

        result = harvester._parse_search_results(records, hostname_filter='data.example.org')

        assert result is None


class TestFAIRsharingHarvestByIdTokenGuard:

    def test_harvest_by_id_without_token_raises_without_any_request(self, monkeypatch):
        harvester = _authenticated_harvester(monkeypatch)
        harvester.jwt_token = None
        harvester.session = mock.Mock()

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest_by_id('some-fairsharing-id')

        assert exc.value.registry == 'fairsharing'
        harvester.session.request.assert_not_called()


def _xml_error_response(status_code):
    """A re3data response whose raise_for_status raises, like a real 4xx/5xx."""
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = {}
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
        f"{status_code} Client Error"
    )
    return resp


class TestRe3DataRecordFetchHonesty:
    """harvest_by_id (the cross-registry bridge and CSV-ID paths) fetches a
    single record; a 5xx there must degrade the repository rather than read
    as a genuine miss. A 404 or unparseable body is a genuinely absent or
    unreadable record and stays a plain None."""

    def test_5xx_on_record_fetch_raises(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _xml_response(503)

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest_by_id('r3d100000001')

        assert exc.value.registry == 're3data'

    def test_404_on_record_fetch_returns_none(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _xml_error_response(404)

        assert harvester.harvest_by_id('r3d100000001') is None

    def test_malformed_record_returns_none(self):
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        harvester.session.request.return_value = _xml_response(200, b'not valid xml')

        assert harvester.harvest_by_id('r3d100000001') is None

    def test_5xx_mid_search_raises_rather_than_being_skipped(self):
        """A 500 on a candidate fetched during the hostname search must be
        reported honestly, not treated like an ordinary bad candidate."""
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        search_xml = b'<list><repository><id>r3d100000001</id><name>First</name></repository></list>'
        harvester.session.request.side_effect = [
            _xml_response(200, search_xml),
            _xml_response(503),
        ]

        with pytest.raises(RegistryUnavailableError) as exc:
            harvester.harvest('https://data.example.org/')

        assert exc.value.registry == 're3data'

    def test_404_search_candidate_is_skipped_and_search_continues(self):
        """A stale bridged ID 404s; the hostname-search loop must skip just
        that candidate and keep going rather than abandoning the search."""
        harvester = Re3DataHarvester()
        harvester.session = mock.Mock()
        search_xml = (
            b'<list>'
            b'<repository><id>r3d100000001</id><name>First</name></repository>'
            b'<repository><id>r3d100000002</id><name>Second</name></repository>'
            b'</list>'
        )
        record_xml = (
            b'<r3d:repository xmlns:r3d="http://www.re3data.org/schema/2-2">'
            b'<r3d:repositoryURL>https://data.example.org/</r3d:repositoryURL>'
            b'<r3d:repositoryName>Second</r3d:repositoryName>'
            b'</r3d:repository>'
        )
        harvester.session.request.side_effect = [
            _xml_response(200, search_xml),
            _xml_error_response(404),
            _xml_response(200, record_xml),
        ]

        result = harvester.harvest('https://data.example.org/')

        assert result is not None
        assert result['title'] == 'Second'
        assert harvester.session.request.call_count == 3


class TestRegistryMetadataSurvivesFailedPageFetch:
    """Registry metadata must be exported even when the landing page is dead.

    In the 2026-08-12 batch, ISSDA, Bgee and Rhea each had a verified re3data
    record and a matched FAIRsharing record, yet exported nothing and reported
    'Metadata: No, Services: 0'. Their landing page fetch had failed, and the
    export path reached its DCAT mapper only through the MetadataHelper built
    from that page. Registry metadata needs no landing page.
    """

    def test_registry_metadata_is_exported_when_page_fetch_failed(self, harvester_credentials):
        harvester = _repo_harvester()
        # The trigger: __init__'s fetch raised, so no page-derived helper exists.
        assert harvester.metadata_helper is None

        harvester.merge_metadata({'title': 'Irish Social Science Data Archive'}, 're3data')
        harvester.merge_metadata({'title': 'Irish Social Science Data Archive'}, 'fairsharing')

        records = harvester.export_and_save(save=False)

        assert [r['@id'] for r in records] == [
            'eden://harvester/re3data/https://example.org/',
            'eden://harvester/fairsharing/https://example.org/',
        ]

    def test_exported_record_carries_the_registry_content(self, harvester_credentials):
        harvester = _repo_harvester()
        harvester.merge_metadata(
            {'title': 'Bgee', 'description': 'Gene expression data'}, 're3data'
        )

        records = harvester.export_and_save(save=False)

        assert len(records) == 1
        topic = records[0]['foaf:primaryTopic']
        assert topic['dct:title'] == 'Bgee'
        assert topic['dct:description'] == 'Gene expression data'
        # The catalog URL still identifies the repository, dead page or not.
        assert topic['@id'] == 'https://example.org/'

    def test_export_makes_no_http_request(self, harvester_credentials):
        """Exporting must not touch the network.

        The page-less MetadataHelper is built without a URL because
        SignPostingHelper fetches any URL it is given, with no timeout. Passing
        one made AgroPortal hang on a dead landing page and fail the whole
        repository in the 2026-08-13 batch - a repository the export fix was
        supposed to rescue, not break.
        """
        harvester = _repo_harvester()
        harvester.merge_metadata({'title': 'AgroPortal'}, 'fairsharing')

        with mock.patch(
            'repo_harvester_server.helper.MetadataHelper.build_session'
        ) as build:
            records = harvester.export_and_save(save=False)

        build.return_value.get.assert_not_called()
        assert len(records) == 1

    def test_successful_fetch_still_uses_the_page_derived_helper(self, harvester_credentials):
        """The fallback must not displace the real helper when the page loaded."""
        harvester = _repo_harvester()
        harvester.metadata_helper = mock.Mock()
        harvester.metadata_helper.export.return_value = {
            'foaf:primaryTopic': {'dct:title': 'From the page helper'}
        }
        harvester.merge_metadata({'title': 'whatever'}, 're3data')

        records = harvester.export_and_save(save=False)

        harvester.metadata_helper.export.assert_called_once()
        assert records[0]['foaf:primaryTopic']['dct:title'] == 'From the page helper'
