from unittest import mock

from repo_harvester_server.helper.MetadataHelper import MetadataHelper


def test_robots_txt_is_read_from_the_host_root():
    session = mock.Mock()
    session.get.return_value.status_code = 200
    session.get.return_value.text = 'Sitemap: https://www.swissubase.ch/sitemap.xml\n'
    helper = MetadataHelper('https://www.swissubase.ch/en/', session=session)

    metadata = helper.get_sitemap_service_metadata()

    session.get.assert_any_call('https://www.swissubase.ch/robots.txt')
    assert metadata['services'][0]['endpoint_uri'] == 'https://www.swissubase.ch/sitemap.xml'
