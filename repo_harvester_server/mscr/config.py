import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 1. API CONSTANTS
MSCR_API_URL = "https://mscr-release.2.rahtiapp.fi/datamodel-api/v2"
MSCR_TIMEOUT = 60

# --- TOGGLE THIS TO FALSE WHEN REAL CROSSWALKS EXIST ---
MOCK_MODE = True 
# -------------------------------------------------------

# 2. CREDENTIAL LOADING
def load_mscr_token():
    """
    Attempts to load the MSCR token from the mscr_credentials.json file.
    """
    current_dir = Path(__file__).parent
    cred_file = current_dir / "mscr_credentials.json"
    
    if cred_file.exists():
        try:
            with open(cred_file, 'r') as f:
                data = json.load(f)
                return data.get("token")
        except Exception as e:
            logger.error(f"Failed to read credentials file: {e}")
    return os.getenv("MSCR_API_TOKEN", None)

MSCR_API_TOKEN = load_mscr_token()

# 3. CROSSWALK REGISTRY CONFIGURATION
# Since they don't exist yet, we leave placeholders. 
# MOCK_MODE=True will bypass the need for valid UUIDs here.
CROSSWALK_IDS = {
    "re3data_to_eden": "00000000-0000-0000-0000-000000000000",
    "schemaorg_to_eden": "00000000-0000-0000-0000-000000000000"
}