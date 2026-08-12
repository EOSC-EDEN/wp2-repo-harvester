"""Tests for the shared registry HTTP helper: backoff on 429, the
distinction between 'no answer' and 'no record', and the one-shot capture of
what a rate-limiting registry actually sends back."""
import logging
from unittest import mock

import pytest
import requests

from repo_harvester_server.helper import RegistryHTTP
from repo_harvester_server.helper.RegistryHTTP import (
    RegistryUnavailableError,
    request_with_backoff,
)


@pytest.fixture(autouse=True)
def _forget_captured_rate_limits():
    """The capture fires once per registry per process; tests are a process."""
    RegistryHTTP._captured_rate_limits.clear()
    yield
    RegistryHTTP._captured_rate_limits.clear()


# Pacing is switched off for the whole suite in conftest.py, which also keeps
# it out of the backoff tests' sleep assertions.


def _response(status_code, headers=None, text=''):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.headers = headers if headers is not None else {}
    resp.text = text
    return resp


def _session(*responses):
    """A session whose .request() returns the given responses in order."""
    session = mock.Mock()
    session.request.side_effect = list(responses)
    return session


class TestRequestWithBackoff:

    def test_success_returns_response_without_sleeping(self):
        session = _session(_response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            resp = request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert resp.status_code == 200
        sleep.assert_not_called()

    def test_non_429_error_status_is_returned_not_raised(self):
        """Callers inspect 401/404 themselves; only 'no answer at all' raises."""
        session = _session(_response(404))
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            resp = request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert resp.status_code == 404

    def test_429_then_success_retries_and_returns(self):
        session = _session(_response(429), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            resp = request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert resp.status_code == 200
        assert session.request.call_count == 2
        sleep.assert_called_once_with(1)  # 2 ** 0

    def test_backoff_is_exponential(self):
        session = _session(_response(429), _response(429), _response(429), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert [c.args[0] for c in sleep.call_args_list] == [1, 2, 4]

    def test_retry_after_header_is_honored(self):
        session = _session(_response(429, {'Retry-After': '7'}), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_called_once_with(7)

    def test_unparseable_retry_after_falls_back_to_exponential(self):
        """FAIRsharing may send an HTTP-date; we must not crash on it."""
        session = _session(
            _response(429, {'Retry-After': 'Wed, 12 Aug 2026 07:00:00 GMT'}),
            _response(200),
        )
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_called_once_with(1)

    def test_retry_after_is_capped(self):
        session = _session(_response(429, {'Retry-After': '99999'}), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_called_once_with(60)

    def test_negative_retry_after_is_clamped_to_zero(self):
        """A nonsensical negative delay must not reach time.sleep()."""
        session = _session(_response(429, {'Retry-After': '-5'}), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            resp = request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert resp.status_code == 200
        sleep.assert_called_once_with(0)

    def test_persistent_429_raises_with_registry_named(self):
        session = _session(*[_response(429) for _ in range(4)])
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError) as exc:
                request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        assert exc.value.registry == 'fairsharing'
        assert '429' in str(exc.value)
        assert session.request.call_count == 4  # 1 initial + 3 retries

    def test_transport_error_raises_immediately(self):
        session = mock.Mock()
        session.request.side_effect = requests.exceptions.ConnectionError('refused')
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError) as exc:
                request_with_backoff(session, 'GET', 'https://x.test/', 're3data')
        assert exc.value.registry == 're3data'
        assert session.request.call_count == 1


class TestProactivePacing:
    """FAIRsharing's limiter is a rolling window, not a rate cap: the batch of
    2026-08-12 tripped it while averaging 0.24 requests/second, then answered
    normally for a minute, then tripped again. Reactive backoff cannot win that
    - 1+2+4 seconds of retrying lands inside the same exhausted window - so the
    harvester has to stay under the budget in the first place."""

    def test_a_request_is_paced_before_it_is_sent(self, monkeypatch):
        monkeypatch.setattr(RegistryHTTP, 'REQUEST_DELAY_SECONDS', 5.0)
        session = _session(_response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_called_once_with(5.0)

    def test_retries_are_paced_too(self, monkeypatch):
        """A retry is another request against the same budget."""
        monkeypatch.setattr(RegistryHTTP, 'REQUEST_DELAY_SECONDS', 5.0)
        session = _session(_response(429), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        # pacing, backoff, pacing again before the retry
        assert [c.args[0] for c in sleep.call_args_list] == [5.0, 1, 5.0]


class TestRateLimitCapture:
    """A 429 is the only evidence we get about a registry's rate limiter, and
    it is discarded the moment we retry. These pin down that we keep it: the
    headers say whether Retry-After is sent, the body says which layer sent it
    (Rack::Attack answers 'Retry later', nginx serves an HTML error page)."""

    def test_first_429_is_logged_with_its_headers_and_body(self, caplog):
        caplog.set_level(logging.WARNING, logger='RegistryHTTP')
        session = _session(
            _response(429, {'Retry-After': '7', 'maintenance': 'false'}, 'Retry later'),
            _response(200),
        )
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')

        assert 'Retry-After' in caplog.text
        assert 'maintenance' in caplog.text
        assert 'Retry later' in caplog.text

    def test_only_the_first_429_per_registry_is_logged(self, caplog):
        """A 98-repository batch must not dump the same block dozens of times."""
        caplog.set_level(logging.WARNING, logger='RegistryHTTP')
        session = _session(
            _response(429, {}, 'DUMPED-BODY'), _response(200),
            _response(429, {}, 'DUMPED-BODY'), _response(200),
        )
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')

        assert caplog.text.count('DUMPED-BODY') == 1

    def test_each_registry_is_captured_separately(self, caplog):
        caplog.set_level(logging.WARNING, logger='RegistryHTTP')
        session = _session(
            _response(429, {}, 'FAIRSHARING-BODY'), _response(200),
            _response(429, {}, 'RE3DATA-BODY'), _response(200),
        )
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            request_with_backoff(session, 'GET', 'https://y.test/', 're3data')

        assert 'FAIRSHARING-BODY' in caplog.text
        assert 'RE3DATA-BODY' in caplog.text

    def test_captured_body_is_truncated(self, caplog):
        """An nginx error page is HTML; we want its shape, not the whole thing."""
        caplog.set_level(logging.WARNING, logger='RegistryHTTP')
        session = _session(_response(429, {}, 'x' * 5000), _response(200))
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')

        assert 'x' * 500 in caplog.text
        assert 'x' * 501 not in caplog.text

    def test_capture_does_not_leak_the_authorization_header(self, caplog):
        """This log gets pasted into mails to the registry. The JWT must not."""
        caplog.set_level(logging.WARNING, logger='RegistryHTTP')
        rate_limited = _response(429, {'Retry-After': '7'}, 'Retry later')
        rate_limited.request.headers = {'Authorization': 'Bearer super-secret-jwt'}
        session = _session(rate_limited, _response(200))
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')

        assert 'Retry later' in caplog.text
        assert 'super-secret-jwt' not in caplog.text

    def test_persistent_429_error_carries_the_response_body(self):
        """After the retries are spent the log line is far away; the degraded
        harvest report must still say what the registry answered."""
        session = _session(*[_response(429, {}, 'Retry later') for _ in range(4)])
        with mock.patch('repo_harvester_server.helper.RegistryHTTP.time.sleep'):
            with pytest.raises(RegistryUnavailableError) as exc:
                request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')

        assert 'Retry later' in str(exc.value)
