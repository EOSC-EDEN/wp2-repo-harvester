import logging
import json
import os
import service_validator # Jens Tool

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

class ServiceInfoHelper(object):
    logger = logging.getLogger('SeviceInfoHelper')

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

    def validate(self):
        1==1

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


