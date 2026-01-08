import connexion
import logging

# 1. Import BOTH harvesters
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester
from repo_harvester_server.mscr.harvester import MSCRHarvester
from repo_harvester_server.models.repository_info import RepositoryInfo

logger = logging.getLogger(__name__)

def get_repo_info(url):  # noqa: E501
    """get_repo_info

    Return the repo info as a dictionary.
    Strategy: Try MSCR (External Transformation) first. If that fails or returns empty, 
    fall back to the legacy local RepositoryHarvester.

    :param url: A repository URL
    :type url: str
    :rtype: RepositoryInfo
    """
    logger.info(f"🚀 Received request to harvest: {url}")
    
    # --- STRATEGY: EXCLUSIONS ---
    # If we know certain URLs MUST use the old logic (e.g. FAIRsharing), skip MSCR.
    if "fairsharing.org" in url:
        logger.info(f"ℹ️  Identified FAIRsharing URL. Skipping MSCR, using Legacy Harvester.")
        return _run_legacy_harvester(url)

    # --- STRATEGY: TRY MSCR ---
    try:
        logger.info("Attempting MSCR Harvest...")
        mscr_harvester = MSCRHarvester(repo_url=url)
        mscr_harvester.harvest()
        
        # Check if we got valid results
        if mscr_harvester.metadata and len(mscr_harvester.metadata.keys()) > 0:
            logger.info("✅ MSCR Harvest successful.")
            return {
                "repoURI": url,
                "metadata": mscr_harvester.metadata,
                "services": mscr_harvester.metadata.get("services", [])
            }
        else:
            logger.warning("⚠️  MSCR returned empty results. Falling back to Legacy.")
            
    except Exception as e:
        logger.error(f"❌ MSCR Harvest failed: {e}. Falling back to Legacy.")

    # --- STRATEGY: FALLBACK TO LEGACY ---
    return _run_legacy_harvester(url)


def _run_legacy_harvester(url):
    """
    Helper function to run the existing/old harvesting logic.
    """
    try:
        logger.info("⏳ Running Legacy RepositoryHarvester...")
        harvester = RepositoryHarvester(url)
        harvester.harvest()
        
        result_metadata = harvester.metadata
        
        # Construct response based on the old schema
        response = {
            "repoURI": url,
            "metadata": result_metadata,
            "services": result_metadata.get("services", [])
        }
        return response

    except Exception as e:
        logger.error(f"❌ Legacy Harvest also failed: {e}")
        return {
            "repoURI": url,
            "error": f"All harvesting methods failed. Legacy error: {str(e)}"
        }, 500