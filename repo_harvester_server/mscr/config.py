import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 1. API CONSTANTS
MSCR_API_URL = "https://mscr-release.2.rahtiapp.fi/datamodel-api/v2"
MSCR_TIMEOUT = 60
MOCK_MODE = False  # Set to False now that we have credentials

# 2. CREDENTIAL LOADING
def load_mscr_token():
    """
    Attempts to load the MSCR token from the mscr_credentials.json file.
    Fallback to Environment variable.
    """
    # Try looking in the local mscr directory based on current file location
    current_dir = Path(__file__).parent
    cred_file = current_dir / "mscr_credentials.json"
    
    # Check if file exists
    if cred_file.exists():
        try:
            with open(cred_file, 'r') as f:
                data = json.load(f)
                token = data.get("token")
                if token:
                    logger.info("Loaded MSCR token from credentials file.")
                    return token
        except Exception as e:
            logger.error(f"Failed to read credentials file: {e}")

    # Fallback to Env
    return os.getenv("MSCR_API_TOKEN", None)

MSCR_API_TOKEN = load_mscr_token()

# 3. CROSSWALK REGISTRY CONFIGURATION
# We will populate these IDs using the helper script in Step 4.
CROSSWALK_IDS = {
    # XML (Re3Data) -> EDEN JSON-LD
    "re3data_to_eden": os.getenv("MSCR_CW_RE3DATA", "REPLACE_WITH_UUID_AFTER_RUNNING_DISCOVERY"),
    
    # JSON-LD (Schema.org) -> EDEN JSON-LD
    "schemaorg_to_eden": os.getenv("MSCR_CW_SCHEMAORG", "REPLACE_WITH_UUID_AFTER_RUNNING_DISCOVERY")
}