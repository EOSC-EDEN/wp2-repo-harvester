import hashlib
import json
import logging
import os
from datetime import datetime, timezone

try:  # stdlib since 3.8; guarded so a source checkout without dist metadata still runs
    from importlib.metadata import PackageNotFoundError, version as _dist_version
except ImportError:  # pragma: no cover
    PackageNotFoundError = Exception

    def _dist_version(_name):
        raise PackageNotFoundError

from eden_validator import ServiceValidator  # Jens' service-validator package (pinned in pyproject.toml)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

# --- DQV metric definitions -------------------------------------------------
# We reuse the W3C DQV *shape* (dqv:QualityMeasurement / dqv:Metric) and the
# ldqd *dimension* (availability). DQV deliberately defines no concrete metrics,
# so we only *name* these two locally as eden:// resources rather than minting a
# whole edenval namespace/ontology. They are embedded inline on every
# measurement so each harmonized graph stays self-describing for the per-graph
# Fuseki->Elastic exporter.
ENDPOINT_AVAILABILITY_METRIC = {
    "@id": "eden://validator/metric/endpointAvailability",
    "@type": "dqv:Metric",
    "skos:definition": {
        "@value": "Checks that the service endpoint is live and responds as expected for its service type.",
        "@language": "en",
    },
    "dqv:inDimension": {"@id": "ldqd:availability"},
    "dqv:expectedDataType": {"@id": "xsd:boolean"},
}
VALIDATION_SCORE_METRIC = {
    "@id": "eden://validator/metric/validationScore",
    "@type": "dqv:Metric",
    "skos:definition": {
        "@value": "EDEN 0-10 endpoint validation score (HTTP status, conformsTo match, media type, body signatures, service title).",
        "@language": "en",
    },
    "dqv:inDimension": {"@id": "ldqd:availability"},
    "dqv:expectedDataType": {"@id": "xsd:decimal"},
}

# --- PROV provenance --------------------------------------------------------
# Who produced a measurement (agent) and in which run (activity). Note rdfs:label,
# not prov:label: PROV-DM lists prov:label as a reserved *attribute* of the abstract
# model, but PROV-O 3.1 encodes it as rdfs:label and defines no prov:label property.
# Like the metric definitions above, both nodes are inlined on every measurement --
# same @id means JSON-LD merges them into one RDF node, which keeps each harmonized
# graph self-describing for the per-graph Fuseki->Elastic exporter.
VALIDATOR_AGENT_URI = "eden://validator"
RUN_URI_PREFIX = "eden://validator/run/"
_RUN_ID_FORMAT = "%Y%m%dT%H%M%SZ"


def _validator_agent():
    """The eden-service-validator as a prov:SoftwareAgent. The version is read from
    the installed distribution so it tracks the pin in pyproject.toml instead of
    drifting; in a source checkout without dist metadata the key is simply omitted."""
    agent = {
        "@id": VALIDATOR_AGENT_URI,
        "@type": "prov:SoftwareAgent",
        "rdfs:label": "EDEN Service Validator",
    }
    try:
        agent["schema:softwareVersion"] = _dist_version("eden-service-validator")
    except PackageNotFoundError:
        pass
    return agent


class ServiceInfoHelper(object):
    logger = logging.getLogger('ServiceInfoHelper')
    _validator = None  # lazily created ServiceValidator, shared across instances

    def __init__(self):
        json_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'service_profiles.json')
        with open(json_path, mode='r', encoding='utf-8') as infofile:
            info_dict = json.load(infofile)
            self.service_profiles = info_dict.get('service_profiles')
            self.profile_specs = {}
            for profile_label, profile in self.service_profiles.items():
                if profile.get('spec_urls'):
                    for spec in profile.get('spec_urls'):
                        if spec.get('url'):
                         self.profile_specs[spec['url']] = {"title": profile["title"], "fairsharing_doi": profile["fairsharing_doi"], "label": profile_label}

    @classmethod
    def _get_validator(cls):
        """Build the ServiceValidator once and reuse it (profiles load only once)."""
        if cls._validator is None:
            profiles_path = os.environ.get('EDEN_SERVICE_PROFILES') or os.path.join(
                os.path.dirname(__file__), '..', 'data', 'service_profiles.json')
            cls._validator = ServiceValidator(profiles_path=profiles_path)
        return cls._validator

    @staticmethod
    def _first(value):
        """Harmonized fields can be scalars or lists; the validator wants scalars."""
        if isinstance(value, list):
            return value[0] if value else None
        return value

    @staticmethod
    def mint_run_id():
        """Identify one validation run. harvest_all mints this once and passes it to
        every repository, so all graphs of a batch share one prov:Activity; the API
        controller lets it default per RepositoryHarvester, since a single-repo
        request genuinely is its own run."""
        return datetime.now(timezone.utc).strftime(_RUN_ID_FORMAT)

    @staticmethod
    def _run_activity(run_id):
        """The prov:Activity node for a run, inlined on every measurement.

        prov:startedAtTime rather than endedAtTime: the run URI is minted when the
        run starts and the per-repository graphs are written while it is still in
        progress, so the end time is not knowable here. Deriving the timestamp from
        run_id also keeps every inlined copy byte-identical -- divergent values under
        one @id would emit conflicting triples instead of merging into one node."""
        activity = {
            "@id": RUN_URI_PREFIX + run_id,
            "@type": "prov:Activity",
            "rdfs:label": "EDEN service validation run",
            "prov:wasAssociatedWith": _validator_agent(),
        }
        try:
            started = datetime.strptime(run_id, _RUN_ID_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            return activity  # caller-supplied id in another shape; skip the timestamp
        activity["prov:startedAtTime"] = {
            "@value": started.isoformat(), "@type": "xsd:dateTime"}
        return activity

    def validate(self, endpoint_uri, expected_type=None, conforms_to=None, service_title=None,
                 run_id=None):
        """Live-validate one service endpoint and return DQV QualityMeasurement
        nodes (JSON-LD dicts) to hang off the dcat:DataService via
        dqv:hasQualityMeasurement. Returns [] when there is nothing to validate
        or the check fails, so harmonization never breaks on a bad endpoint."""
        if not endpoint_uri:
            return []
        try:
            result = self._get_validator().validate_url(
                endpoint_uri,
                expected_type=self._first(expected_type),
                conforms_to=self._first(conforms_to),
                service_title=self._first(service_title),
            )
        except Exception as e:
            self.logger.warning('Validation failed for %s: %s', endpoint_uri, str(e))
            return []
        return self._to_dqv(endpoint_uri, result, run_id=run_id)

    @staticmethod
    def _to_dqv(endpoint_uri, result, run_id=None):
        """Map a validator result dict into DQV QualityMeasurement nodes. Without a
        run_id the measurements carry no prov:wasGeneratedBy at all, rather than
        half-formed provenance pointing at an invented run."""
        generated_at = datetime.now(timezone.utc).isoformat()
        stamp = hashlib.sha1(endpoint_uri.encode('utf-8')).hexdigest()[:12]
        # One shared dict per call: identical inlined copies merge into one RDF node.
        activity = ServiceInfoHelper._run_activity(run_id) if run_id else None

        def measurement(suffix, metric, value):
            node = {
                "@id": "eden://validator/measurement/{}-{}".format(stamp, suffix),
                "@type": "dqv:QualityMeasurement",
                "dqv:isMeasurementOf": metric,
                "dqv:computedOn": {"@id": endpoint_uri},
                "dqv:value": value,
                "prov:generatedAtTime": {"@value": generated_at, "@type": "xsd:dateTime"},
            }
            if activity:
                node["prov:wasGeneratedBy"] = activity
            return node

        measurements = []
        if result.get('valid') is not None:
            measurements.append(measurement(
                'valid', ENDPOINT_AVAILABILITY_METRIC,
                {"@value": str(bool(result['valid'])).lower(), "@type": "xsd:boolean"}))
        score = result.get('score')
        if isinstance(score, (int, float)):
            measurements.append(measurement(
                'score', VALIDATION_SCORE_METRIC,
                {"@value": "{:.1f}".format(score), "@type": "xsd:decimal"}))
        return measurements

    def type(self, name_or_url):
        if self.service_profiles.get(name_or_url):
            return name_or_url
        else:
            if self.profile_specs.get(name_or_url):
                return self.profile_specs[name_or_url].get('label')
            else:
                return None

    def conforms_to(self, name):
        if self.service_profiles.get(name):
            try:
                return self.service_profiles[name]['spec_urls'][0]['url']
            except Exception as  e:
                self.logger.info('Failed to find service profile {} : {}'.format(name, str(e)))
                return None
