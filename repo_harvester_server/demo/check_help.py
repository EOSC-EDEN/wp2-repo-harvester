"""Copy for the "What is this?" toggles in the report (#44).

Each 'quotes' entry is verbatim text from the specification named in its
'source', reproduced for attribution. 'checked' states what this harvester
reads.
"""

CHECK_HELP = {
    'embedded_jsonld': {
        'quotes': [
            {
                'text': (
                    'Schema.org is a collaborative, community activity with a '
                    'mission to create, maintain, and promote schemas for '
                    'structured data on the Internet, on web pages, in email '
                    'messages, and beyond. [...] Many applications from '
                    'Google, Microsoft, Pinterest, Yandex and others already '
                    'use these vocabularies to power rich, extensible '
                    'experiences.'
                ),
                'source': 'Schema.org',
                'url': 'https://schema.org/',
            },
            {
                'text': (
                    'This specification defines JSON-LD 1.1, a '
                    'JSON-based format to serialize Linked Data.'
                ),
                'source': 'JSON-LD 1.1, W3C Recommendation',
                'url': 'https://www.w3.org/TR/json-ld11/',
            },
        ],
        'checked': 'A <script type="application/ld+json"> element in the page.',
        'examples': [
            {
                'code': '''<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "DataCatalog",
  "name": "Example Data Repository",
  "url": "https://data.example.org/",
  "description": "Open research data from Example University.",
  "publisher": {"@type": "Organization", "name": "Example University"},
  "license": "https://creativecommons.org/licenses/by/4.0/"
}
</script>''',
            },
        ],
    },
    'meta_tags': {
        'quotes': [
            {
                'text': (
                    'This document describes how Dublin Core metadata can be '
                    'encoded in HTML/XHTML <meta> and <link> elements.'
                ),
                'source': 'Expressing Dublin Core in HTML/XHTML meta and link elements, DCMI',
                'url': 'https://www.dublincore.org/specifications/dublin-core/dcq-html/',
            },
        ],
        'checked': (
            'The meta names title, description, publisher, license, contact, '
            'language and type.'
        ),
        'examples': [
            {
                'code': '''<meta name="title" content="Example Data Repository">
<meta name="description" content="Open research data from Example University.">
<meta name="publisher" content="Example University">
<meta name="license" content="https://creativecommons.org/licenses/by/4.0/">
<meta name="contact" content="data@example.org">
<meta name="language" content="en">
<meta name="type" content="Dataset">''',
            },
        ],
    },
    'linked_jsonld': {
        'quotes': [
            {
                'text': (
                    'The Signposting site started in 2016 by recommending '
                    'patterns, based on typed links, that repositories can '
                    'implement to make it easier for machines to navigate the '
                    'scholarly objects they host. For example, use describedby '
                    'links to point from an object\'s landing page to metadata '
                    'descriptions of the object, and item links to point at '
                    'the object\'s actual content resources.'
                ),
                'source': 'Signposting the Scholarly Web',
                'url': 'https://signposting.org/',
            },
        ],
        'checked': (
            'A describedby link typed application/ld+json, in the HTTP Link '
            'header or the page head. Up to ten are followed.'
        ),
        'examples': [
            {
                'caption': 'As a response header:',
                'code': '''Link: <https://data.example.org/records/42/metadata.jsonld>
      ; rel="describedby" ; type="application/ld+json"''',
            },
            {
                'caption': 'Or in the page head:',
                'code': '''<link rel="describedby" type="application/ld+json"
      href="https://data.example.org/records/42/metadata.jsonld">''',
            },
        ],
    },
    'fairicat_services': {
        'quotes': [
            {
                'text': (
                    'Discovering whether and which interoperability '
                    'affordances are provided by a repository remains a '
                    'challenge. [...] They can be used in automatic '
                    'processes by clients that are looking for specific '
                    'approaches to interoperate with a repository, e.g. via '
                    'OAI-PMH, SPARQL, Sitemaps, Linked Data Notifications.'
                ),
                'source': 'FAIRiCat: Supporting Discovery of a Repository\'s '
                          'Interoperability Affordances',
                'url': 'https://signposting.org/FAIRiCat/',
            },
            {
                'text': (
                    'This specification defines two formats and associated '
                    'media types for representing sets of links as '
                    'standalone documents.'
                ),
                'source': 'RFC 9264, Linkset',
                'url': 'https://www.rfc-editor.org/rfc/rfc9264.html',
            },
        ],
        'checked': (
            'An api-catalog link typed application/linkset+json, and the '
            'service-doc and service-meta links in the linkset it points to.'
        ),
        'examples': [
            {
                'caption': 'On the landing page (or as a Link header):',
                'code': '''<link rel="api-catalog" type="application/linkset+json"
      href="https://data.example.org/.well-known/api-catalog">''',
            },
            {
                'caption': 'The catalog itself, one entry per interface:',
                'code': '''{
  "linkset": [
    {
      "anchor": "https://data.example.org/oai",
      "service-doc": [
        {"href": "https://www.openarchives.org/OAI/openarchivesprotocol.html"}
      ],
      "service-meta": [
        {"href": "https://data.example.org/oai?verb=Identify",
         "type": "application/xml", "title": "OAI-PMH 2.0"}
      ]
    }
  ]
}''',
            },
        ],
    },
    'feed_services': {
        'quotes': [
            {
                'text': (
                    'Atom is an XML-based document format that describes lists '
                    'of related information known as "feeds". Feeds are '
                    'composed of a number of items, known as "entries", each '
                    'with an extensible set of attached metadata. [...] The '
                    'primary use case that Atom addresses is the syndication '
                    'of Web content such as weblogs and news headlines to Web '
                    'sites as well as directly to user agents.'
                ),
                'source': 'RFC 4287, The Atom Syndication Format',
                'url': 'https://www.rfc-editor.org/rfc/rfc4287.html',
            },
            {
                'text': (
                    'RSS autodiscovery is a technique that makes it possible '
                    'for browsers and other software to automatically find a '
                    'site\'s RSS feed, whether it\'s in RSS 1.0 or RSS 2.0 '
                    'format. [...] This specification describes how web '
                    'publishers can support autodiscovery by adding an HTML '
                    'header to web pages.'
                ),
                'source': 'RSS Autodiscovery, RSS Advisory Board',
                'url': 'https://www.rssboard.org/rss-autodiscovery',
            },
        ],
        'checked': (
            'An alternate link typed application/atom+xml or '
            'application/rss+xml.'
        ),
        'examples': [
            {
                'code': '''<link rel="alternate" type="application/atom+xml"
      title="New deposits" href="https://data.example.org/feed.atom">''',
            },
        ],
    },
    'sitemap_service': {
        'quotes': [
            {
                'text': (
                    'Sitemaps are an easy way for webmasters to inform search '
                    'engines about pages on their sites that are available '
                    'for crawling.'
                ),
                'source': 'sitemaps.org',
                'url': 'https://www.sitemaps.org/',
            },
        ],
        'checked': 'The first Sitemap line in robots.txt.',
        'examples': [
            {
                'caption': 'https://data.example.org/robots.txt',
                'code': '''User-agent: *
Allow: /

Sitemap: https://data.example.org/sitemap.xml''',
            },
        ],
    },
    'open_search': {
        'quotes': [
            {
                'text': (
                    'Search clients can use OpenSearch description documents '
                    'to learn about the public interface of a search engine.'
                ),
                'source': 'OpenSearch 1.1 Draft 6',
                'url': 'https://github.com/dewitt/opensearch/blob/master/opensearch-1-1-draft-6.md',
            },
        ],
        'checked': (
            'A search link typed application/opensearchdescription+xml.'
        ),
        'examples': [
            {
                'caption': 'On the landing page:',
                'code': '''<link rel="search" type="application/opensearchdescription+xml"
      title="Example Data Repository"
      href="https://data.example.org/opensearch.xml">''',
            },
            {
                'caption': 'https://data.example.org/opensearch.xml',
                'code': '''<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">
  <ShortName>Example Data</ShortName>
  <Description>Search datasets in the Example Data Repository.</Description>
  <Url type="application/atom+xml"
       template="https://data.example.org/search?q={searchTerms}&amp;format=atom"/>
</OpenSearchDescription>''',
            },
        ],
    },
}


def help_for(source):
    return CHECK_HELP.get(source)
