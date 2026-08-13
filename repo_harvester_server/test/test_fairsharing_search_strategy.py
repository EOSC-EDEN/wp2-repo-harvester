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
from unittest import mock

from repo_harvester_server.helper.FAIRsharingHarvester import FAIRsharingHarvester
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
