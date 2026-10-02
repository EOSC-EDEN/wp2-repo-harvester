"""Cleanup shared by every source of certificate dicts: page JSON-LD and re3data."""
import re

DOI_PATTERN = re.compile(r'\b10\.\d{4,9}/[^\s"<>&?#]+')


def clean_certificate(raw):
    """Plain strings, plus `active` when it is a real bool; None means unknown
    and is left out.

    url becomes an IRI in the export, and a relative IRI can make FUSEKI reject
    the whole graph, so anything that is not http(s) is dropped rather than
    guessed at. A url carrying a DOI becomes https://doi.org/<DOI>: re3data links
    CoreTrustSeal certificates by their DataverseNL page, repositories by the
    resolver, and the harmonizer merges claims on url."""
    cert = {k: v.strip() for k, v in raw.items()
            if k != 'active' and isinstance(v, str) and v.strip()}
    if isinstance(raw.get('active'), bool):
        cert['active'] = raw['active']
    if not cert.get('url', '').startswith(('http://', 'https://')):
        cert.pop('url', None)
    doi = DOI_PATTERN.search(cert.get('url', ''))
    if doi:
        cert['url'] = 'https://doi.org/' + doi.group()
    if not (cert.get('url') or cert.get('issuer') or cert.get('name')):
        return {}
    return cert
