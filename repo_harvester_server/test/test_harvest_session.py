"""Tests for the guarded HTTP session: no private targets, no unbounded waits.

The interesting cases are the indirect ones. The harvester follows redirects
and fetches URLs discovered inside the page it was given, so the guard has to
hold for every hop, not just for the URL a user typed into the form.
"""
import socket
from unittest import mock

import pytest
import requests
from requests.adapters import HTTPAdapter

from repo_harvester_server.helper.HarvestSession import (
    ALLOW_PRIVATE_TARGETS_ENV,
    DEFAULT_TIMEOUT,
    BlockedTargetError,
    assert_target_allowed,
    build_session,
)

_ADDRESSES = {
    'public.example': '93.184.216.34',
    'internal.example': '10.0.0.5',
    'localhost': '127.0.0.1',
    'metadata.example': '169.254.169.254',
    'lan.example': '192.168.1.10',
}


def _fake_getaddrinfo(host, port, *args, **kwargs):
    if host not in _ADDRESSES:
        raise socket.gaierror(f'unknown host {host}')
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (_ADDRESSES[host], port or 80))]


@pytest.fixture(autouse=True)
def _resolver():
    with mock.patch(
        'repo_harvester_server.helper.HarvestSession.socket.getaddrinfo',
        side_effect=_fake_getaddrinfo,
    ):
        yield


def _response(status, url, location=None):
    """A response requests can carry through resolve_redirects.

    raw=None is deliberate: requests short-circuits cookie extraction and
    content reading when there is no raw stream, which is what makes these
    tests work without a socket.
    """
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp.raw = None
    if location:
        resp.headers['Location'] = location
    return resp


class TestSchemeGuard:

    @pytest.mark.parametrize('url', [
        'file:///etc/passwd',
        'ftp://public.example/pub',
        'gopher://public.example/',
    ])
    def test_non_http_scheme_is_refused(self, url):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed(url)

    def test_url_without_a_host_is_refused(self):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('http:///no-host')

    def test_malformed_ipv6_literal_is_refused(self):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('http://[::1/path')


class TestAddressGuard:

    @pytest.mark.parametrize('url', [
        'http://localhost/',
        'http://internal.example/',
        'http://lan.example/admin',
        'http://metadata.example/latest/meta-data/',
    ])
    def test_non_public_address_is_refused(self, url):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed(url)

    def test_instance_metadata_address_is_named_in_the_message(self):
        with pytest.raises(BlockedTargetError) as exc:
            assert_target_allowed('http://metadata.example/latest/meta-data/')
        assert '169.254.169.254' in str(exc.value)

    def test_public_address_is_allowed(self):
        assert_target_allowed('https://public.example/repository')  # must not raise

    def test_unresolvable_host_is_refused(self):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('https://nowhere.example/')

    def test_escape_hatch_allows_private_targets(self, monkeypatch):
        monkeypatch.setenv(ALLOW_PRIVATE_TARGETS_ENV, '1')
        assert_target_allowed('http://localhost:8000/index.html')  # must not raise

    def test_escape_hatch_does_not_lift_the_scheme_guard(self, monkeypatch):
        monkeypatch.setenv(ALLOW_PRIVATE_TARGETS_ENV, '1')
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('file:///etc/passwd')

    def test_non_numeric_port_is_refused(self):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('http://public.example:abc/')

    def test_out_of_range_port_is_refused(self):
        with pytest.raises(BlockedTargetError):
            assert_target_allowed('http://public.example:99999/')


class TestSessionBehaviour:

    def test_default_timeout_is_applied_when_the_caller_passes_none(self):
        seen = {}

        def _send(self, request, **kwargs):
            seen.update(kwargs)
            return _response(200, request.url)

        with mock.patch.object(HTTPAdapter, 'send', _send):
            build_session().get('https://public.example/')

        assert seen['timeout'] == DEFAULT_TIMEOUT

    def test_explicit_timeout_is_preserved(self):
        seen = {}

        def _send(self, request, **kwargs):
            seen.update(kwargs)
            return _response(200, request.url)

        with mock.patch.object(HTTPAdapter, 'send', _send):
            build_session().get('https://public.example/', timeout=3)

        assert seen['timeout'] == 3

    def test_redirect_into_private_space_is_blocked(self):
        """The hop matters, not the URL the user submitted."""
        def _send(self, request, **kwargs):
            if 'public.example' in request.url:
                return _response(302, request.url, 'http://internal.example/secret')
            return _response(200, request.url)

        with mock.patch.object(HTTPAdapter, 'send', _send):
            with pytest.raises(BlockedTargetError):
                build_session().get('https://public.example/')

    def test_session_carries_the_project_user_agent(self):
        assert 'EDEN-Harvester' in build_session().headers['User-Agent']


from repo_harvester_server.helper.MetadataHelper import MetadataHelper
from repo_harvester_server.helper.SignPostingHelper import SignPostingHelper


class TestHelpersUseTheGuardedSession:
    """Every helper that reaches the open web must go through one session."""

    def test_signposting_helper_uses_the_injected_session(self):
        session = mock.Mock()
        session.get.return_value = _response(200, 'https://public.example/')

        SignPostingHelper('https://public.example/', session=session)

        session.get.assert_called_once_with('https://public.example/')

    def test_signposting_helper_builds_a_guarded_session_by_default(self):
        with mock.patch(
            'repo_harvester_server.helper.SignPostingHelper.build_session'
        ) as build:
            build.return_value.get.return_value = _response(200, 'https://public.example/')
            SignPostingHelper('https://public.example/')
        build.assert_called_once()

    def test_metadata_helper_passes_its_session_to_signposting(self):
        session = mock.Mock()
        helper = MetadataHelper('https://public.example/', b'<html></html>', {}, session=session)
        assert helper.signposting_helper.session is session

    def test_robots_txt_fetch_uses_the_session(self):
        session = mock.Mock()
        session.get.return_value = _response(200, 'https://public.example/robots.txt')
        session.get.return_value._content = b''
        helper = MetadataHelper('https://public.example/', b'<html></html>', {}, session=session)

        helper.get_sitemap_service_metadata()

        session.get.assert_called_with('https://public.example/robots.txt')
