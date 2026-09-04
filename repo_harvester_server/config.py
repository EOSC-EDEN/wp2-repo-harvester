import os

# The Graph Store endpoint. Persistence is on by default: an unset FUSEKI_PATH
# writes to the local default below, which is what batch runs, the JSON API and
# developer machines have always done. Turning it off is the explicit choice -
# set FUSEKI_PATH to an empty value and nothing is persisted or harmonized, and
# the harvester does not ask for FUSEKI credentials it will never use. That is
# the public demo's configuration, where there is no triple store at all.
#
# Default-on because the two mistakes are not symmetric: a stateless deployment
# that wrongly tries to write fails loudly on its first request, while a
# persisting one that wrongly stays silent still looks healthy and simply stops
# filling the store.
_FUSEKI_PATH_ENV = os.environ.get("FUSEKI_PATH")

FUSEKI_PATH = _FUSEKI_PATH_ENV or "http://localhost:3030/service_registry_store/data"

# Unset means "not configured": persist, using the default above. Set but empty
# means "deliberately no triple store": do not persist.
PERSISTENCE_ENABLED = _FUSEKI_PATH_ENV is None or bool(_FUSEKI_PATH_ENV.strip())

# Which registries a harvest may consult. FAIRsharing stays off on the public
# demo until the EDEN service account exists; re3data needs no credentials and
# has never rate-limited us, so it can be on from the start. Both by default,
# which is what batch harvesting wants.
ENABLED_REGISTRIES = tuple(
    name.strip().lower()
    for name in os.environ.get("EDEN_ENABLED_REGISTRIES", "re3data,fairsharing").split(",")
    if name.strip()
)
