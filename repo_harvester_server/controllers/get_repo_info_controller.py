import logging

from repo_harvester_server.demo.service import (
    HarvesterBusyError,
    run_interactive_harvest,
)

logger = logging.getLogger('GetRepoInfoController')


def get_repo_info(url):  # noqa: E501
    """get_repo_info

    Return the repo info as a dictionary

    :param url: A repository URL
    :type url: str

    :rtype: RepositoryInfo
    """
    logger.info("Received request to harvest: %s", url)

    try:
        report = run_interactive_harvest(url)
        records = report['records']
        return {
            "repoURI": report['canonical_url'],
            "metadata": records[0] if records else {},
            "services": report['services'],
        }
    except HarvesterBusyError as e:
        # Recoverable and the caller's business: 503 invites a retry, 500 does not.
        return {"repoURI": url, "error": str(e)}, 503
    except Exception as e:
        # Public endpoint: log the real exception server-side, but never hand
        # the caller its text back - it can disclose internal paths or hosts.
        logger.error("Error harvesting %s: %s", url, e, exc_info=True)
        return {"repoURI": url, "error": "The harvest could not be completed."}, 500
