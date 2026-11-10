from unittest import mock

import pytest
import requests
from flask import Flask, render_template

from repo_harvester_server.demo.service import build_report
from repo_harvester_server.demo.views import demo_blueprint
from repo_harvester_server.helper.HarvestTime import display_timestamp, literal_value
from repo_harvester_server.helper.RegistryCache import RegistryCache
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


@pytest.fixture(autouse=True)
def harvester_credentials(monkeypatch):
    monkeypatch.setenv('FAIRSHARING_USERNAME', 'user')
    monkeypatch.setenv('FAIRSHARING_PASSWORD', 'secret')
    monkeypatch.setenv('FUSEKI_USERNAME', 'fuseki')
    monkeypatch.setenv('FUSEKI_PASSWORD', 'secret')


def _repo_harvester(**kwargs):
    session = mock.Mock()
    session.get.side_effect = requests.exceptions.ConnectionError('no network in tests')
    kwargs.setdefault('session', session)
    return RepositoryHarvester('https://example.org/', **kwargs)


def test_exported_date_is_typed_utc():
    harvester = _repo_harvester()
    harvester.merge_metadata({'title': 'From the page'}, 'embedded_jsonld')

    [record] = harvester.export_and_save(save=False)

    issued = record['dct:issued']
    assert issued['@type'] == 'xsd:dateTime'
    assert issued['@value'].endswith('+00:00')
    assert record['prov:wasGeneratedBy']['prov:startedAtTime'] == issued


def test_each_record_keeps_its_own_time():
    harvester = _repo_harvester()
    harvester.harvested_at = '2026-11-05T14:00:00+00:00'
    harvester.merge_metadata({'title': 'From the page'}, 'embedded_jsonld')
    harvester.merge_metadata({'title': 'From re3data'}, 're3data',
                             '2026-11-05T13:30:00+00:00')

    page, registry = harvester.export_and_save(save=False)

    assert literal_value(page['dct:issued']) == '2026-11-05T14:00:00+00:00'
    assert literal_value(registry['dct:issued']) == '2026-11-05T13:30:00+00:00'


def test_cached_registry_answer_keeps_the_time_it_was_fetched():
    cache = RegistryCache()
    first = _repo_harvester(registry_cache=cache, enabled_registries=['re3data'])
    first.re3data_harvester = mock.Mock()
    first.re3data_harvester.harvest.return_value = {'title': 'Bgee'}
    with mock.patch(
        'repo_harvester_server.helper.RepositoryHarvester.harvest_timestamp',
        return_value='2026-11-05T13:00:00+00:00',
    ):
        first.harvest_registry_metadata()

    second = _repo_harvester(registry_cache=cache, enabled_registries=['re3data'])
    second.re3data_harvester = mock.Mock()
    second.harvest_registry_metadata()

    second.re3data_harvester.harvest.assert_not_called()
    [record] = second.export_and_save(save=False)
    assert literal_value(record['dct:issued']) == '2026-11-05T13:00:00+00:00'


def test_page_shows_page_and_registry_times():
    harvester = _repo_harvester(enabled_registries=['re3data'])
    harvester.harvested_at = '2026-11-05T14:00:00+00:00'
    harvester.merge_metadata({'title': 'Bgee'}, 're3data', '2026-11-05T13:00:00+00:00')
    records = harvester.export_and_save(save=False)
    report = build_report(harvester, 'https://example.org/', records)
    report['page_fetched'] = True

    app = Flask(__name__)
    app.register_blueprint(demo_blueprint)
    with app.test_request_context('/'):
        html = render_template('index.html', submitted_url='https://example.org/',
                               report=report)

    assert 'on 2026-11-05 14:00 UTC' in html
    assert 'harvested\n2026-11-05 13:00 UTC' in html


def test_naive_time_is_not_passed_off_as_utc():
    assert display_timestamp('2026-11-05T14:03:07') == '2026-11-05 14:03 (server time)'
