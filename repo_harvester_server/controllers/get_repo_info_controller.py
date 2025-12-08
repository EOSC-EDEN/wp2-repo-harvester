import connexion
from repo_harvester_server.helper.RepositoryHarvester import CatalogMetadataHarvester
from repo_harvester_server.models.repository_info import RepositoryInfo

def get_repo_info(url):  # noqa: E501
    """get_repo_info

    Return the repo info as a dictionary

    :param url: A repository URL
    :type url: str

    :rtype: RepositoryInfo
    """
    print(f"Received request to harvest: {url}")
    
    try:
        # 1. Instantiate the harvester for the requested URL
        harvester = CatalogMetadataHarvester(url)
        
        # 2. Run the harvest process
        harvester.harvest()
        
        # 3. Get the resulting metadata (using the logic from our new MetadataHelper)
        result_metadata = harvester.metadata
        
        # 4. Construct the response object (matching swagger definition)
        # Note: We wrap the raw metadata into the 'metadata' field of the response
        response = {
            "repoURI": url,
            "metadata": result_metadata,
            "services": result_metadata.get("services", []) # Extract services if present
        }
        
        return response

    except Exception as e:
        # Simple error handling
        print(f"Error harvesting {url}: {e}")
        return {
            "repoURI": url,
            "error": str(e)
        }, 500