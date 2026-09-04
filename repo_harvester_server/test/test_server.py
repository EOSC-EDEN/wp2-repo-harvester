import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
import requests
import pytest
import os

from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester


@pytest.fixture(scope="module")
def http_server():
    # Serve files from the "web" directory
    web_dir = os.path.join(os.path.dirname(__file__), "./web")
    # The guard refuses non-public addresses; this fixture deliberately serves
    # the page under test on localhost.
    os.environ['EDEN_ALLOW_PRIVATE_TARGETS'] = '1'
    os.chdir(web_dir)

    PORT = 8000
    server = HTTPServer(('localhost', PORT), SimpleHTTPRequestHandler)

    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    # Give the server a moment to start
    time.sleep(0.5)

    yield f"http://localhost:{PORT}"

    os.environ.pop('EDEN_ALLOW_PRIVATE_TARGETS', None)
    server.shutdown()
    thread.join()

def test_basic(http_server):
    #basic html has only one meta tag
    url = f"{http_server}/index.html"
    harvester = RepositoryHarvester(url)
    result = harvester.harvest()
    #print(result[0].get('prov:wasGeneratedBy').get('@id'))
    assert len(result) > 0
    assert result[0].get('prov:wasGeneratedBy').get('@id') == 'eden://harvester/meta_tags'

def test_index_page(http_server):
    url = f"{http_server}/index.html"
    response = requests.get(url)
    assert response.status_code == 200
    assert "Hello, world!" in response.text
