#!/usr/bin/env python3

import connexion
import os
from flask import current_app

def create_app():
    # Point to the location of swagger.yaml inside the package
    base_dir = os.path.abspath(os.path.dirname(__file__))
    swagger_dir = os.path.join(base_dir, 'repo_harvester_server', 'swagger')

    app = connexion.App(__name__, specification_dir=swagger_dir)
    app.add_api('swagger.yaml', arguments={'title': 'RepoInfoHarvester'}, pythonic_params=True)
    
    return app

def main():
    app = create_app()
    print("Starting Harvester Server on port 8080...")
    app.run(port=8080)

if __name__ == '__main__':
    main()