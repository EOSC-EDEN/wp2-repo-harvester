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
  "dct:publisher": publisher[].{
    "@type": 'foaf:Agent',
    "foaf:name" : name,
    "vcard:country": country      
  },
  "dct:description": description,
  "dct:language": language,
  "dct:contactPoint": contact,
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
  "dct:conformsTo": policies[].{
  "@id": policy_uri,
  "@type": 'dct:Policy',
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