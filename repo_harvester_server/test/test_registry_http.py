"""Tests for the shared registry HTTP helper: backoff on 429, the
distinction between 'no answer' and 'no record', and the one-shot capture of
what a rate-limiting registry actually sends back."""
import logging
import threading
import time
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
    harvester has to stay under the budget in the first place.

    The gate measures the interval since the previous *response*, rather than
    sleeping unconditionally before every request, so REQUEST_DELAY_SECONDS
    becomes a hard ceiling on request rate (60/pacing per minute) instead of
    only a floor with slack on top. A tight back-to-back pair - a 429 retry,
    or the two search strategies tried for one repository - behaves exactly
    like the old flat sleep, because there is no elapsed time to subtract;
    everywhere else the gate waits less, all the way down to nothing at all
    for a registry's first request of the run."""

    def test_the_first_request_is_not_delayed(self, monkeypatch):
        """Nothing has been asked of this registry, so there is nothing to wait
        for. The old unconditional sleep taxed every cold harvest 5s a request
        for no benefit."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 5.0}
        )
        RegistryHTTP.reset_pacing_state()
        session = _session(_response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_not_called()

    def test_a_following_request_waits_out_the_interval(self, monkeypatch):
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 5.0}
        )
        RegistryHTTP.reset_pacing_state()
        # The gate reads the clock once after each response, and once before a
        # request that has something to wait for - so the very first request
        # consumes no value at all. Here: mark_done after request 1, then
        # wait_turn before request 2 sees 1.0, then mark_done after request 2.
        clock = iter([0.0, 1.0, 1.0])
        monkeypatch.setattr(RegistryHTTP, '_monotonic', lambda: next(clock))
        session = _session(_response(200), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        # 1 second has passed since the first response, so 4 remain.
        sleep.assert_called_once_with(4.0)

    def test_no_wait_once_the_interval_has_already_elapsed(self, monkeypatch):
        """A visitor arriving on a quiet service pays nothing."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 5.0}
        )
        RegistryHTTP.reset_pacing_state()
        clock = iter([0.0, 60.0, 60.0])
        monkeypatch.setattr(RegistryHTTP, '_monotonic', lambda: next(clock))
        session = _session(_response(200), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        sleep.assert_not_called()

    def test_retries_are_paced_too(self, monkeypatch):
        """A retry is another request against the same budget - and the
        backoff before it must not be swallowed into the pacing interval.

        Uses the same 429,429,429,200 sequence as test_backoff_is_exponential
        so the escalating 1,2,4s backoff is visible here too. Each clock value
        is the moment one _monotonic() call in the gate would see it, on the
        assumption that every mocked sleep() "took" exactly as long as it was
        asked to and nothing else consumes time in between - the tightest
        case a real batch can produce. If the backoff's own mark_done() were
        missing, wait_turn() would measure from *before* the backoff instead
        of after it, and every retry would collapse to a flat 5.0s gap
        regardless of attempt number instead of escalating - see the
        assertion below.
        """
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 5.0}
        )
        RegistryHTTP.reset_pacing_state()
        clock = iter([
            0.0,         # mark_done after response 1 (429)
            1.0, 1.0,    # mark_done after backoff(1); wait_turn before request 2
            6.0,         # mark_done after response 2 (429)
            8.0, 8.0,    # mark_done after backoff(2); wait_turn before request 3
            13.0,        # mark_done after response 3 (429)
            17.0, 17.0,  # mark_done after backoff(4); wait_turn before request 4
            22.0,        # mark_done after response 4 (200)
        ])
        monkeypatch.setattr(RegistryHTTP, '_monotonic', lambda: next(clock))
        session = _session(
            _response(429), _response(429), _response(429), _response(200)
        )
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
        # No wait before the first request. Then, for each 429: the backoff
        # (1, 2, 4s - exponential, per _retry_after_seconds), followed by the
        # gate topping up to the full 5.0s pacing interval measured from the
        # end of that backoff, not from the original response. The total gap
        # between one response and the next request therefore escalates
        # (1+5=6, 2+5=7, 4+5=9) exactly like the old unconditional sleep,
        # instead of collapsing to a flat 5s regardless of attempt number.
        assert [c.args[0] for c in sleep.call_args_list] == [
            1, 5.0, 2, 5.0, 4, 5.0,
        ]

    def test_registries_are_paced_independently(self, monkeypatch):
        """Pacing one registry must not tax another - each keeps its own
        gate and its own clock.

        Both registries here are configured with a delay, so both take the
        gated path; calling an *unmeasured* registry instead (pacing=0) would
        take the ungated path regardless of whether gates are kept separate,
        and would only duplicate test_an_unmeasured_registry_is_not_paced
        rather than proving independence."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS',
            {'fairsharing': 5.0, 'datacite': 5.0},
        )
        RegistryHTTP.reset_pacing_state()
        session = _session(_response(200), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            request_with_backoff(session, 'GET', 'https://z.test/', 'datacite')
        # Both calls are each registry's own first-ever request, so neither
        # has anything to wait for - unless the two shared one gate, in which
        # case datacite would inherit fairsharing's just-set timestamp and
        # wait out most of the 5.0s interval instead.
        sleep.assert_not_called()

    def test_an_unmeasured_registry_is_not_paced(self, monkeypatch):
        """We only pace registries we have measured. Guessing a delay for a new
        one would slow batches down for no evidence."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 5.0}
        )
        RegistryHTTP.reset_pacing_state()
        session = _session(_response(200), _response(200))
        with mock.patch(
            'repo_harvester_server.helper.RegistryHTTP.time.sleep'
        ) as sleep:
            request_with_backoff(session, 'GET', 'https://z.test/', 'datacite')
            request_with_backoff(session, 'GET', 'https://z.test/', 'datacite')
        sleep.assert_not_called()

    def test_threads_do_not_each_get_their_own_budget(self, monkeypatch):
        """Four harvest slots meant four independent sleepers, and four times
        the request rate the pacing figure was calibrated for.

        Real timing, with the interval turned right down. Patching sleep here
        would be self-defeating: RegistryHTTP.time IS the stdlib time module,
        so the patch would also neutralise the delay this test uses to create
        the overlap it is looking for, and the assertion would hold whether the
        gate worked or not."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 0.01}
        )
        RegistryHTTP.reset_pacing_state()
        concurrent = []
        inside = []
        inside_lock = threading.Lock()

        class _CountingSession:
            def request(self, method, url, **kwargs):
                with inside_lock:
                    inside.append(1)
                    concurrent.append(len(inside))
                time.sleep(0.05)
                with inside_lock:
                    inside.pop()
                return _response(200)

        session = _CountingSession()
        results = []
        results_lock = threading.Lock()

        def _run():
            request_with_backoff(session, 'POST', 'https://x.test/', 'fairsharing')
            with results_lock:
                results.append(1)

        threads = [threading.Thread(target=_run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        # A thread that raised - e.g. hit an unexpected exception rather than
        # completing normally - would otherwise vanish silently: join() does
        # not surface it, and max(concurrent) == 1 would still hold trivially
        # true with only three (or fewer) threads ever entering
        # _CountingSession.request at all. Confirm all four actually ran.
        assert len(results) == 4
        assert max(concurrent) == 1

    def test_an_ungated_registry_is_not_serialised(self, monkeypatch):
        """re3data has no measured limit, so it must not queue behind itself -
        that would cost the demo latency to enforce a limit nobody imposed.

        Deterministic rather than timing-probabilistic: a Barrier only opens
        once all four threads have reached the request. If the gate wrongly
        serialised re3data, the threads queue one at a time behind a lock
        instead of arriving together, and the barrier's own timeout breaks it
        - failing the test for the right reason, with no timing margin to
        tune and nothing to flake."""
        monkeypatch.setattr(
            RegistryHTTP, 'REQUEST_DELAY_SECONDS', {'fairsharing': 0.01}
        )
        RegistryHTTP.reset_pacing_state()
        barrier = threading.Barrier(4, timeout=5)

        class _CountingSession:
            def request(self, method, url, **kwargs):
                barrier.wait()
                return _response(200)

        session = _CountingSession()
        results = []
        results_lock = threading.Lock()

        def _run():
            request_with_backoff(session, 'GET', 'https://y.test/', 're3data')
            with results_lock:
                results.append(1)

        threads = [threading.Thread(target=_run) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        # If the gate wrongly serialised re3data, only one thread would ever
        # reach barrier.wait() at a time; the other three would be stuck
        # acquiring a lock instead, the barrier's 4-party rendezvous would
        # never complete, and BrokenBarrierError would propagate out of
        # every thread once the barrier's own 5s timeout fires - so none of
        # the four would reach results.append.
        assert len(results) == 4


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
