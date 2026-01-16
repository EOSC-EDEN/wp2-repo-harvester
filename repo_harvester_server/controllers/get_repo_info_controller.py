import connexion
from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester
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
        harvester = RepositoryHarvester(url)

        # 2. Run the harvest process - returns list of exported DCAT records
        exported_records = harvester.harvest()

        # 3. Collect all services from all exported records
        #    Services are nested in prov:hadPrimarySource.dcat:service
        all_services = []
        for record in exported_records:
            if isinstance(record, dict):
                # Check top-level
                services = record.get("dcat:service", [])
                if isinstance(services, list):
                    all_services.extend(services)
                elif services:
                    all_services.append(services)

                # Check nested in prov:hadPrimarySource
                primary_source = record.get("prov:hadPrimarySource", {})
                if isinstance(primary_source, dict):
                    nested_services = primary_source.get("dcat:service", [])
                    if isinstance(nested_services, list):
                        all_services.extend(nested_services)
                    elif nested_services:
                        all_services.append(nested_services)

        # 4. Construct the response object (matching swagger definition)
        response = {
            "repoURI": harvester.catalog_url,
            "metadata": exported_records[0] if exported_records else {},
            "services": all_services
        }

        return response

    except Exception as e:
        # Simple error handling
        print(f"Error harvesting {url}: {e}")
        return {
            "repoURI": url,
            "error": str(e)
        }, 500