#!/usr/bin/env python3

import connexion
from flask import current_app
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester
# from repo_harvester_server import encoder

def create_app():
    app = connexion.App(__name__, specification_dir='swagger/')
    app.add_api('swagger.yaml', arguments={'title': 'RepoInfoHarvester'}, pythonic_params=True)
    
    with app.app.app_context():
        # CORRECTED USAGE: Initialize RepositoryHarvester
        # This seems to initialize a global instance ('termtagger') for the app context.
        # We keep the hardcoded URL if it's required for initialization/loading vocabularies.
        current_app.termtagger = RepositoryHarvester('https://www.pangaea.de')
        
    return app

def main():
    app = create_app()
    app.run(port=8080)


if __name__ == '__main__':
    main()