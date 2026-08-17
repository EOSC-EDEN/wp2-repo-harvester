#!/usr/bin/env python3
"""Development entry point. The application itself lives in the package, so an
installed copy can be served without the checkout: see repo_harvester_server/app.py.
"""
from repo_harvester_server.app import create_app, main

if __name__ == '__main__':
    main()
