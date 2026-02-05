GET_ALL_GRAPHS ='''
SELECT DISTINCT ?g
WHERE {
  GRAPH ?g {
    ?s ?p ?o
  }
}
ORDER BY ?g
'''


def GET_DISTINCT_GRAPH(graph_uri: str) -> str:
    """
    Returns a SPARQL query string like BASIC_SPARQL
    but restricted to the given named graph URI.
    """
    query = f'''
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        PREFIX dcat: <http://www.w3.org/ns/dcat#>
        PREFIX dct:  <http://purl.org/dc/terms/>
        PREFIX vcard: <http://www.w3.org/2006/vcard/ns#>
        
        SELECT DISTINCT ?catalog ?title ?description ?publisher_name ?publisher_country ?contact_email ?contact_telephone ?contact_url ?license
        WHERE {{
          GRAPH <{graph_uri}> {{
            OPTIONAL {{ ?catalog dct:title ?title }}
            OPTIONAL {{ ?catalog dct:description ?description }}
        
            OPTIONAL {{ ?catalog dct:publisher ?publisher .
              OPTIONAL {{ ?publisher foaf:name ?publisher_name }}
              OPTIONAL {{ ?publisher vcard:country ?publisher_country }}
            }}
            OPTIONAL {{ ?catalog dct:license ?license }}
        
            OPTIONAL {{
              ?catalog dct:contactPoint ?contact .
              OPTIONAL {{ ?contact vcard:hasEmail ?contact_email }}
              OPTIONAL {{ ?contact vcard:telephone ?contact_telephone }}
              OPTIONAL {{ ?contact vcard:url ?contact_url }}
            }}
          }}
        }}
        ORDER BY ?catalog ?title
        '''
    return query
