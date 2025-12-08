#!/bin/bash

# Define the list of repositories to harvest
# Format: "Filename_Prefix|URL"
REPOS=(
    "pangaea|https://pangaea.de"
    "zenodo|https://zenodo.org"
    "dans_ssh|https://ssh.datastations.nl"
    "fdr_can|https://www.frdr-dfdr.ca/repo/"
)

# Base URL of your local harvester server
API_URL="http://localhost:8080/?url="
OUTPUT_DIR="output"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

echo "🌾 Starting Batch Harvest..."
echo "--------------------------------"

for entry in "${REPOS[@]}"; do
    # Split the string by "|"
    NAME="${entry%%|*}"
    URL="${entry##*|}"
    
    FILEPATH="$OUTPUT_DIR/${NAME}.json"
    
    echo "Processing: $NAME ($URL)"
    
    # Run Curl and save output
    # -s: Silent mode
    curl -s "${API_URL}${URL}" > "$FILEPATH"
    
    # Check if the file is empty or valid JSON
    if [[ -s "$FILEPATH" ]]; then
        echo "✅ Saved to $FILEPATH"
    else
        echo "❌ Failed to harvest $URL"
    fi
done

echo "--------------------------------"
echo "🎉 Harvest complete. Check the '$OUTPUT_DIR' folder."