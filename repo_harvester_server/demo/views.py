"""The human face: a form, and a rendering of one harvest.

Server-rendered Jinja on a Flask blueprint mounted beside the connexion app.
No build step, no frontend framework, no change to swagger.yaml.
"""
import logging
import os

from flask import Blueprint, render_template, request, send_from_directory

from repo_harvester_server.demo.service import (
    HarvesterBusyError,
    run_interactive_harvest,
)

logger = logging.getLogger('DemoViews')

demo_blueprint = Blueprint(
    'demo', __name__, template_folder='templates'
)

_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')


@demo_blueprint.get('/')
def index():
    """The form, and - when a URL was submitted - the report for it."""
    submitted_url = (request.args.get('url') or '').strip()
    if not submitted_url:
        # Covers both the first visit and a whitespace-only submission.
        message = None if 'url' not in request.args else \
            'Please enter a repository landing page URL.'
        return render_template('index.html', submitted_url='', message=message)

    try:
        report = run_interactive_harvest(submitted_url)
    except HarvesterBusyError as e:
        return render_template(
            'index.html', submitted_url=submitted_url, message=str(e)
        ), 503
    except Exception:
        # The page is public: an arbitrary exception message can disclose
        # internal paths or hostnames, so the visitor gets a generic notice
        # while the full detail goes to the server log only.
        logger.error(
            "Error harvesting %s", submitted_url, exc_info=True
        )
        return render_template(
            'index.html', submitted_url=submitted_url,
            message="That harvest could not be completed. This is not "
                    "something you did wrong - please try again in a moment.",
        ), 500

    return render_template('index.html', submitted_url=submitted_url, report=report)


@demo_blueprint.get('/healthz')
def healthz():
    """Liveness only. It must never harvest: it is polled, harvests are slow."""
    return {'status': 'ok'}


@demo_blueprint.get('/favicon.ico')
def favicon():
    """Browsers ask for this unprompted; answering it keeps one 404 warning per
    visitor out of the log, where it would bury the warnings that matter."""
    return send_from_directory(_STATIC_DIR, 'favicon.svg', mimetype='image/svg+xml')


@demo_blueprint.get('/logo-eden.svg')
def logo():
    """The project logo, shown in the page header."""
    return send_from_directory(_STATIC_DIR, 'logo-eden.svg', mimetype='image/svg+xml')
