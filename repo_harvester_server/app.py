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
    """Development and container entry point. Production runs uvicorn against
    `app` above, with the systemd unit passing --host 127.0.0.1 explicitly.

    This binds 0.0.0.0 on purpose: the Dockerfile's CMD runs this function, so
    a container's published port needs it listening on all interfaces, not
    just loopback inside the container's own network namespace - binding
    127.0.0.1 here makes a published port connect to nothing, and the
    HEALTHCHECK (which runs inside the same container) would still report
    healthy while nothing outside the container could reach it. Do not
    "harden" this back to 127.0.0.1; that is the systemd unit's job, not
    this function's.
    """
    # Print a URL that can actually be opened. uvicorn logs the bind address it
    # was given, and 0.0.0.0 is a wildcard meaning "every interface", not a
    # destination - browsers will not open it.
    print("Starting Harvester Server: http://127.0.0.1:8080/")
    print("Bound to all interfaces, so it is reachable from your network too.")
    app.run(host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
