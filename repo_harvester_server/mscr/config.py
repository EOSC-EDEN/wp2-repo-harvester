import os

"""
Configuration for the MSCR (Metadata Schema & Crosswalk Registry) Module.
Production Environment: mscr-release.2.rahtiapp.fi
"""

# The base URL for the API
MSCR_API_URL = "https://mscr-release.2.rahtiapp.fi/datamodel-api/v2"

# Security: Get token from Environment Variable
# Export in terminal: export MSCR_API_TOKEN="your-token-from-ui"
MSCR_API_TOKEN = os.getenv("MSCR_API_TOKEN", "PASTE_YOUR_TOKEN_HERE_IF_TESTING_LOCALLY")

# Timeout for API requests in seconds
MSCR_TIMEOUT = 60

# CROSSWALK REGISTRY
# Look up these UUIDs in the MSCR UI and paste here
# For now, these are placeholders.
CROSSWALK_IDS = {
    # Case 1: re3data XML -> EDEN JSON-LD
    "re3data_to_eden": "REPLACE-WITH-REAL-UUID-FROM-MSCR-UI",
    
    # Case 2: Generic Schema.org -> EDEN JSON-LD
    "schemaorg_to_eden": "REPLACE-WITH-REAL-UUID-FROM-MSCR-UI"
}

# Toggle Mock Mode (Set to False to use the real URL above)
MOCK_MODE = False
