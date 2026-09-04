"""Tests for the search term FAIRsharing's fallback name search actually sends.

Strategy 2 searches FAIRsharing by repository name. The batch runner has known
the real name all along (it names the output file with it) but never passed it
down, so the harvester guessed one from the hostname instead - and a bad guess
is expensive. The run of 2026-08-12 asked FAIRsharing for 'www' five times, and
the only two requests in the whole run that timed out were the guesses 'data'
and 'repository'. Those queries also cannot succeed: results are filtered on a
hostname match that a generic word will never produce.
"""
import json
import threading
import time
from unittest import mock

import pytest

from repo_harvester_server.helper import FAIRsharingHarvester as fs_module
from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
from repo_harvester_server.helper.RegistryHTTP import RegistryUnavailableError
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


def _no_results():
    resp = mock.Mock()
    resp.status_code = 200
    resp.headers = {}
    resp.text = ''
    resp.json.return_value = {'data': []}
    resp.raise_for_status.return_value = None
    return resp


def _harvester():
    """A signed-in harvester whose session records every outgoing search."""
    with mock.patch.object(FAIRsharingHarvester, '_authenticate', autospec=True):
        harvester = FAIRsharingHarvester()
    harvester.jwt_token = 'token-1'
    harvester.session = mock.Mock()
    harvester.session.request.return_value = _no_results()
    return harvester


def _queries_sent(harvester):
    """The 'q' of every search actually posted to FAIRsharing."""
    return [
        json.loads(call.kwargs['data'])['q']
        for call in harvester.session.request.call_args_list
    ]


class TestFallbackSearchTerm:

    def test_the_real_repository_name_is_used_when_known(self):
        harvester = _harvester()
        harvester.harvest('https://www.progedo.fr/en/home/', 'PROGEDO')
        assert _queries_sent(harvester) == ['www.progedo.fr', 'PROGEDO']

    def test_www_is_never_sent_as_a_search_term(self):
        """Without a name we still guess, but never at the infrastructure label."""
        harvester = _harvester()
        harvester.harvest('https://www.gesis.org/en/data-services')
        assert _queries_sent(harvester) == ['www.gesis.org', 'gesis']

    def test_an_infrastructure_label_is_stepped_over(self):
        harvester = _harvester()
        harvester.harvest('https://data.dtu.dk/')
        assert _queries_sent(harvester) == ['data.dtu.dk', 'dtu']

    def test_no_fallback_search_when_nothing_distinctive_remains(self):
        """Discarding 'repository' from repository.cern leaves only the public
        suffix, which is not a name. Asking anyway cost a 15-second timeout."""
        harvester = _harvester()
        harvester.harvest('https://repository.cern/')
        assert _queries_sent(harvester) == ['repository.cern']

    def test_a_distinctive_first_label_is_still_used(self):
        """Guard: 'cds' is the repository's own acronym, not infrastructure,
        and this guess found the Copernicus record on 2026-08-12."""
        harvester = _harvester()
        harvester.harvest('https://cds.climate.copernicus.eu/')
        assert _queries_sent(harvester) == ['cds.climate.copernicus.eu', 'cds']

    def test_ordinary_hostnames_are_unchanged(self):
        """Guard: the risk of this change is suppressing useful searches."""
        harvester = _harvester()
        harvester.harvest('https://infraart.inoe.ro/')
        assert _queries_sent(harvester) == ['infraart.inoe.ro', 'infraart']

    def test_single_label_hostname_gets_no_fallback_search(self):
        harvester = _harvester()
        harvester.harvest('https://localhost/')
        assert _queries_sent(harvester) == ['localhost']

    def test_database_is_stepped_over(self):
        """Observed on the live demo, 2026-09-01: database.inspee.gr sent
        FAIRsharing the single word 'database' and timed out at 15s, twice.
        The label set held 'data' and 'db' but not 'database'. Stepping over it
        also yields the better term - 'inspee' is the repository's own name."""
        harvester = _harvester()
        harvester.harvest('https://database.inspee.gr/')
        assert _queries_sent(harvester) == ['database.inspee.gr', 'inspee']

    def test_a_repository_platform_name_is_stepped_over(self):
        """EPrints is repository software, not a repository. Searching for it
        matches every EPrints-based record and none survives the hostname
        filter; 'uklo' is the institution, which is what we actually want."""
        harvester = _harvester()
        harvester.harvest('https://eprints.uklo.edu.mk/')
        assert _queries_sent(harvester) == ['eprints.uklo.edu.mk', 'uklo']


class TestRepositoryNameReachesTheRegistry:
    """The name is only useful if it survives the trip from the batch runner."""

    def test_repository_harvester_passes_the_name_to_fairsharing(self):
        re3data = mock.Mock()
        re3data.harvest.return_value = None
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = None

        harvester = RepositoryHarvester(
            'https://www.progedo.fr/en/home/',
            re3data_harvester=re3data,
            fairsharing_harvester=fairsharing,
            repository_name='PROGEDO',
        )
        harvester.harvest_registry_metadata()

        fairsharing.harvest.assert_called_once_with(
            'https://www.progedo.fr/en/home/', 'PROGEDO'
        )

    def test_name_is_optional_for_callers_that_only_have_a_url(self):
        """The connexion controller harvests a bare URL; that must still work."""
        re3data = mock.Mock()
        re3data.harvest.return_value = None
        fairsharing = mock.Mock()
        fairsharing.harvest.return_value = None

        harvester = RepositoryHarvester(
            'https://www.progedo.fr/en/home/',
            re3data_harvester=re3data,
            fairsharing_harvester=fairsharing,
        )
        harvester.harvest_registry_metadata()

        fairsharing.harvest.assert_called_once_with(
            'https://www.progedo.fr/en/home/', None
        )


def _harvester_without_signin():
    """A harvester that never touches the network during construction."""
    with mock.patch.object(fs_module.FAIRsharingHarvester, '_authenticate'):
        harvester = fs_module.FAIRsharingHarvester()
    harvester.jwt_token = 'test-token'
    return harvester


class TestSharedBetweenThreads:
    """One harvester now serves every visitor, so its session and its JWT are
    touched by four worker threads. requests.Session is not documented
    thread-safe, and the read-token / request / re-auth / retry sequence has to
    be atomic or two threads both 401 and one overwrites the other's fresher
    token."""

    def test_only_one_thread_is_inside_harvest_at_a_time(self):
        harvester = _harvester_without_signin()
        concurrent = []
        inside = []
        inside_lock = threading.Lock()
        searches = []

        def slow_search(query, hostname_filter=None, expected_doi=None):
            with inside_lock:
                inside.append(1)
                concurrent.append(len(inside))
                searches.append(query)
            time.sleep(0.05)
            with inside_lock:
                inside.pop()
            return None

        harvester._search_fairsharing = slow_search
        threads = [
            threading.Thread(
                target=lambda: harvester.harvest('https://gesis.org/')
            )
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
            # A thread that died early (e.g. on an unhandled exception in the
            # target) would leave harvest()'s work undone but still let
            # max(concurrent) == 1 pass trivially - a dead thread never gets
            # inside slow_search to contend anything.
            assert not t.is_alive()

        assert max(concurrent) == 1
        # slow_search always returns None, so every thread runs both of
        # harvest()'s strategies: the hostname 'gesis.org' itself, then the
        # name _name_from_hostname() guesses from it. Ask the real method for
        # that guess instead of hardcoding what it returns, so this stays
        # correct if the guessing logic ever changes.
        guessed_name = harvester._name_from_hostname('gesis.org')
        assert guessed_name, (
            "test assumes a fallback guess is made; adjust the URL if this "
            "ever stops being true"
        )
        expected_searches = ['gesis.org', guessed_name] * 4
        assert sorted(searches) == sorted(expected_searches)

    def test_a_thread_that_waits_too_long_degrades(self):
        """Bounded wait: better a page that honestly says FAIRsharing could not
        be consulted than one that runs past the reverse proxy's timeout."""
        harvester = _harvester_without_signin()
        holder_in = threading.Event()
        holder_out = threading.Event()

        def hold():
            with harvester._lock:
                holder_in.set()
                holder_out.wait(5)

        holder = threading.Thread(target=hold)
        holder.start()
        assert holder_in.wait(5)

        with mock.patch.object(fs_module, 'LOCK_TIMEOUT_SECONDS', 0.05):
            with pytest.raises(RegistryUnavailableError) as excinfo:
                harvester.harvest('https://gesis.org/')

        holder_out.set()
        holder.join(10)
        assert excinfo.value.registry == 'fairsharing'

    def test_re_authentication_from_inside_a_harvest_does_not_deadlock(self):
        """harvest -> _search_fairsharing -> _authenticate re-enters the lock,
        which is why it is an RLock and not a Lock."""
        harvester = _harvester_without_signin()
        calls = []

        def search_that_reauthenticates(query, hostname_filter=None,
                                        expected_doi=None):
            harvester._authenticate()
            calls.append(query)
            return None

        harvester._search_fairsharing = search_that_reauthenticates
        with mock.patch.dict('os.environ', {}, clear=True):
            harvester.harvest('https://gesis.org/')

        assert calls

    def test_the_lock_is_released_when_a_harvest_raises(self):
        """The harvester is about to be shared for the life of the process.
        _serialized()'s try/finally makes release-on-exception correct by
        construction, but if that ever regressed, a single raised harvest
        would wedge the lock forever - every later visitor would degrade,
        permanently, not just this one request."""
        harvester = _harvester_without_signin()
        harvester.jwt_token = None  # harvest() raises before doing anything else

        with pytest.raises(RegistryUnavailableError):
            harvester.harvest('https://gesis.org/')

        # _lock is an RLock, reentrant per-thread: acquiring it again from
        # this same thread would succeed trivially even if release() never
        # ran, because the thread that "leaked" it is also the thread
        # probing it. That would only prove this thread survived the raise,
        # not that the lock is actually free for the next visitor - who
        # runs on a different thread. Probe from a different thread instead,
        # and release from that same thread too: RLock requires the thread
        # that released it to be the one that holds it.
        acquired_elsewhere = []

        def try_acquire_and_release():
            got_it = harvester._lock.acquire(timeout=0.5)
            acquired_elsewhere.append(got_it)
            if got_it:
                harvester._lock.release()

        prober = threading.Thread(target=try_acquire_and_release)
        prober.start()
        prober.join(2)

        assert acquired_elsewhere == [True], "lock was not released"
