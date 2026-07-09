import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from eden_validator import ServiceValidator  # Jens' service-validator package (pinned in requirements.txt)

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

    def validate(self, endpoint_uri, expected_type=None, conforms_to=None, service_title=None):
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
        return self._to_dqv(endpoint_uri, result)

    @staticmethod
    def _to_dqv(endpoint_uri, result):
        """Map a validator result dict into DQV QualityMeasurement nodes."""
        generated_at = datetime.now(timezone.utc).isoformat()
        stamp = hashlib.sha1(endpoint_uri.encode('utf-8')).hexdigest()[:12]
        measurements = []
        if result.get('valid') is not None:
            measurements.append({
                "@id": "eden://validator/measurement/{}-valid".format(stamp),
                "@type": "dqv:QualityMeasurement",
                "dqv:isMeasurementOf": ENDPOINT_AVAILABILITY_METRIC,
                "dqv:computedOn": {"@id": endpoint_uri},
                "dqv:value": {"@value": str(bool(result['valid'])).lower(), "@type": "xsd:boolean"},
                "prov:generatedAtTime": {"@value": generated_at, "@type": "xsd:dateTime"},
            })
        score = result.get('score')
        if isinstance(score, (int, float)):
            measurements.append({
                "@id": "eden://validator/measurement/{}-score".format(stamp),
                "@type": "dqv:QualityMeasurement",
                "dqv:isMeasurementOf": VALIDATION_SCORE_METRIC,
                "dqv:computedOn": {"@id": endpoint_uri},
                "dqv:value": {"@value": "{:.1f}".format(score), "@type": "xsd:decimal"},
                "prov:generatedAtTime": {"@value": generated_at, "@type": "xsd:dateTime"},
            })
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
