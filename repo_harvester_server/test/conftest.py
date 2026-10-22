"""Shared test fixtures.

The harvester paces its registry requests to stay inside FAIRsharing's rolling
budget (see RegistryHTTP.REQUEST_DELAY_SECONDS). That delay is real time, and
every test that reaches request_with_backoff would otherwise pay it - the suite
went from seconds to minutes when pacing was switched on. Tests are not the
thing being paced, so pacing is off by default; the tests that assert pacing
behaviour set the constant themselves.

Pacing also carries state now - when each registry was last called - which
would otherwise leak from one test into the next.
"""
import pytest

from repo_harvester_server.helper import RegistryHTTP
from repo_harvester_server.helper.CoreTrustSealHarvester import CoreTrustSealHarvester


@pytest.fixture(autouse=True)
def _no_proactive_pacing(monkeypatch):
    monkeypatch.setattr(RegistryHTTP, 'REQUEST_DELAY_SECONDS', {})
    RegistryHTTP.reset_pacing_state()
    yield
    RegistryHTTP.reset_pacing_state()


@pytest.fixture(autouse=True)
def _no_live_coretrustseal(monkeypatch):
    # CoreTrustSeal is on by default, so every test that harvests with the
    # default registries would fetch its whole certificate list. A test that
    # needs entries sets _fetch on its own instance, which wins over this.
    monkeypatch.setattr(CoreTrustSealHarvester, '_fetch', lambda self: [])
