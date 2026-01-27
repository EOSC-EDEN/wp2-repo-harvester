# a jmespath query to retrieve all basic info from a repo JSON-LD
# which previously was harmonised / simplified by the GraphHelper

DCAT_EXPORT_QUERY = '''
{
  "@context": {
    "dcat": 'http://www.w3.org/ns/dcat#',
    "dct":  'http://purl.org/dc/terms/',
    "schema" : 'http://schema.org/',
    "vcard": 'http://www.w3.org/2006/vcard/ns#',
    "foaf": 'http://xmlns.com/foaf/0.1/',
    "prov": 'http://www.w3.org/ns/prov#'
  },
   "@type": 'dcat:CatalogRecord',
   "prov:wasGeneratedBy":{
       "@type": 'prov:Activity',
       "prov:name": 'Metadata harvesting and extraction activity'
   },
   "prov:wasAssociatedWith":{
   "@type": 'prov:SoftwareAgent',
   "prov:label" : 'EDEN Catalog Service Harvester'
   },
   "prov:hadPrimarySource": {
  "@type": ['dcat:Catalog', 'foaf:Project'],
  "dct:title": title,
  "dct:identifier": identifier,
  "dct:publisher": ([publisher] || publisher[])[].{
  "@type": 'foaf:Agent', 
  "foaf:name":name,
  "vcard:country":country||address.addressCountry
  },
  "dct:description": description,
  "dct:language": language,
  "dct:contactPoint": (contact||contact[0]).{
      "@type": 'vcard:Kind',
      "vcard:telephone": telephone || null,"vcard:fn": fn || null,
      "vcard:hasEmail": hasEmail || email || (contains(to_string(@), '@') && @) || null, 
      "vcard:url": url || (contains(to_string(@), 'http') && @) || null
  },
  "dct:license": license || null,
  "dcat:keyword": [subject, keywords, theme][],
  "dcat:service": services[].{
      "@id": endpoint_uri,
      "@type": 'dcat:DataService',
      "dcat:endpointURL": endpoint_uri,
      "dct:conformsTo": conforms_to,
      "dct:title": title,
      "dct:format": output_format,
      "dct:description": validation_status
  },
  "dct:conformsTo": policies[?policy_uri].{
  "@idss": policy_uri,
  "@type": ['dct:Policy', type]
  "dct:title": title
  }
}}
'''

REPO_INFO_QUERY = '''{
title: name || headline[*]."@value" || headline || title || null,
identifier: ["@id" , identifier][] ,
resource_type: "@type",
publisher: [(publisher || provider)] | [].{name: (name || @), country: ("country-name" || address.addressCountry || null)} ,
description: description || abstract || null,
language: inLanguage || language || null,
access_terms: accessRights || conditionsOfAccess || ((isAccessibleForFree || free) == `true` && 'unrestricted' || (isAccessibleForFree || free) == `false` && 'restricted' || null),
contact: contactPoint || null,
subject: [subjects, keyword, theme][],
license: license.url ||license."@id" || license.id || license.name || license || null 
}
'''

# a jmespath query to retrieve service info
SERVICE_INFO_QUERY  = '''{
endpoint_uri : url || target || endpointURL || landingPage || null,
type : "@type",
title : title || name || null,
output_format: serviceOutput.identifier || mediaType || null,
conforms_to: documentation || conformsTo
}'''

POLICY_INFO_QUERY = '''{
policy_uri:  url || "@id",
type : ["@type", additionalType][],
title: title || name || null
}'''

FAIRSHARING_QUERY ='''
{
    title: attributes.metadata.name || null,
    identifier: [attributes.metadata.doi, attributes.metadata.cross_references[?portal=='re3data'].url][] || null,
    resource_type:  attributes.record_type || null,
    publisher:  [attributes.organisation_links[?relation=='maintains'][].{name: organisation_name} , attributes.grants[?relation=='maintains'][].{name: saved_state.name} ][] || null,
    description: attributes.metadata.description || null,
    access_terms: attributes.metadata.data_access_condition.type|| null,
    contact : attributes.metadata.contacts[].{mail: contact_email},
    subject: attributes.subjects[],
    license: attributes.licence_links[?relation!='undefined'].licence_url || null ,
    policies: [
        attributes.metadata.data_preservation_policy.{type: 'premis:PreservationPolicy', policy_uri:url, title: name},
        attributes.metadata.data_deposition_condition.{type: 'ex:DepositionPolicy', policy_uri:url, title: name},
        attributes.metadata.resource_sustainability.{type: 'ex:SustainabilityPolicy', policy_uri:url, title:name}
    ]
}
'''