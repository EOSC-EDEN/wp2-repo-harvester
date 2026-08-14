import os

# The Graph Store endpoint. An unset FUSEKI_PATH means there is no triple store
# at all - the public demo's configuration - so nothing is persisted and the
# harvester must not ask for FUSEKI credentials it will never use. Set it (the
# local default below is the usual value) to turn persistence back on.
_FUSEKI_PATH_ENV = os.environ.get("FUSEKI_PATH")

FUSEKI_PATH = _FUSEKI_PATH_ENV or "http://localhost:3030/service_registry_store/data"

PERSISTENCE_ENABLED = bool(_FUSEKI_PATH_ENV)

# Which registries a harvest may consult. FAIRsharing stays off on the public
# demo until the EDEN service account exists; re3data needs no credentials and
# has never rate-limited us, so it can be on from the start. Both by default,
# which is what batch harvesting wants.
ENABLED_REGISTRIES = tuple(
    name.strip().lower()
    for name in os.environ.get("EDEN_ENABLED_REGISTRIES", "re3data,fairsharing").split(",")
    if name.strip()
)
