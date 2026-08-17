#!/usr/bin/env python3
"""The application: the JSON API and the HTML page, served by one process.

The connexion API is mounted under /api so the human page can own /. That is a
call-site argument to add_api, not an edit to swagger.yaml - the API contract
is unchanged, and its own `servers: - url: /` entry stays correct relative to
the mount point.
"""
import os

import connexion
from connexion.options import SwaggerUIOptions

from repo_harvester_server.demo.views import demo_blueprint

API_BASE_PATH = '/api'


def create_app():
    """Build the application: connexion under /api, the demo page at /."""
    package_dir = os.path.abspath(os.path.dirname(__file__))
    swagger_dir = os.path.join(package_dir, 'swagger')

    app = connexion.FlaskApp(__name__, specification_dir=swagger_dir)
    app.add_api(
        'swagger.yaml',
        base_path=API_BASE_PATH,
        arguments={'title': 'RepoInfoHarvester'},
        pythonic_params=True,
        swagger_ui_options=SwaggerUIOptions(swagger_ui_path='/ui'),
    )
    app.app.register_blueprint(demo_blueprint)
    return app


# Module-level so a process manager can serve it directly:
#   uvicorn repo_harvester_server.app:app --host 127.0.0.1 --port 8080
app = create_app()


def main():
    """Development server. Production runs uvicorn against `app` above."""
    print("Starting Harvester Server on port 8080...")
    app.run(host='127.0.0.1', port=8080)


if __name__ == '__main__':
    main()
