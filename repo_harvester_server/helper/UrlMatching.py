"""URL and hostname comparison shared by the registry harvesters.

Both re3data and FAIRsharing answer a search with several records that sit on
the same host, and both then have to decide which one the submitted URL
actually means. That decision is the same problem in both registries, so the
comparison lives here rather than once per harvester.

Reducing a URL to its hostname is what made the harvester attach PRIDE's
metadata to https://www.ebi.ac.uk/biosamples/: the path is the only thing
telling those two apart. Everything here keeps the path.
"""
import logging
from urllib.parse import parse_qsl, urlparse

logger = logging.getLogger('UrlMatching')


def normalize_hostname(hostname):
    """Lowercase a hostname and drop a leading 'www.'."""
    if not hostname:
        return None
    hostname = hostname.casefold()
    if hostname.startswith('www.'):
        hostname = hostname[4:]
    return hostname


def hostnames_match(query_hostname, record_hostname):
    """Whether two hostnames name the same site.

    Exact after normalization, or one a direct subdomain of the other -
    'about.coscine.de' and 'coscine.de' are the same site, but a two-level
    difference is not assumed to be.
    """
    h1 = normalize_hostname(query_hostname)
    h2 = normalize_hostname(record_hostname)
    if not h1 or not h2:
        return False
    if h1 == h2:
        return True

    h1_parts = h1.split('.')
    h2_parts = h2.split('.')
    if abs(len(h1_parts) - len(h2_parts)) == 1:
        if h1.endswith('.' + h2) or h2.endswith('.' + h1):
            return True
    return False


def normalize_url(url):
    """Prepare a URL for comparison without losing its path or parameters.

    Ignores what cannot distinguish two repositories - scheme, hostname case,
    a leading 'www.', a fragment, a default port, a trailing slash - and keeps
    what can: the path and the query.

    Returns None for a URL that cannot be parsed, so callers can tell "these
    differ" from "this one could not be read".
    """
    if not url:
        return None
    parsed = urlparse(url.strip())
    hostname = normalize_hostname(parsed.hostname)
    try:
        port = parsed.port
    except ValueError:
        logger.warning("Skipping URL with invalid port: %s", url)
        return None
    default_port = {'http': 80, 'https': 443}.get(parsed.scheme.casefold())
    if port == default_port:
        port = None
    path = parsed.path or '/'
    if path != '/':
        path = path.rstrip('/')
    query = tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return hostname, port, path, query


def urls_match(first_url, second_url):
    """Whether two URLs point at the same repository."""
    first = normalize_url(first_url)
    second = normalize_url(second_url)
    return first is not None and second is not None and first == second


def url_score(catalog_urls, candidate_url, host_matcher=hostnames_match):
    """Score how closely a registry record's URL matches the submitted ones.

    3: the same URL.
    2: same host, and one path contains the other - a repository's landing
       page and the deeper page a registry recorded for it.
    1: same host only.
    0: no relation, or a URL that could not be read.

    ``host_matcher`` exists because re3data's caller accepts several hostnames
    joined by '|' in one string and has to match any of them.
    """
    candidate = normalize_url(candidate_url)
    if candidate is None:
        return 0
    if any(urls_match(candidate_url, url) for url in catalog_urls):
        return 3

    candidate_hostname, candidate_port, candidate_path, _ = candidate
    best_score = 0
    for catalog_url in catalog_urls:
        normalized_url = normalize_url(catalog_url)
        if normalized_url is None:
            continue
        hostname, port, path, _ = normalized_url
        if not host_matcher(hostname or '', candidate_hostname):
            continue
        if port != candidate_port:
            continue
        best_score = max(best_score, 1)
        if path != '/' and candidate_path != '/' and (
            path == candidate_path
            or path.startswith(candidate_path + '/')
            or candidate_path.startswith(path + '/')
        ):
            best_score = 2
    return best_score


def best_by_url(candidates, catalog_urls, url_of, host_matcher=hostnames_match):
    """Pick the one candidate whose URL best matches, or None if it is a tie.

    ``candidates`` is any sequence; ``url_of`` reads the URL out of one of
    them. Returns (winner, scored) where ``scored`` is [(score, candidate)]
    for logging - a caller that has to explain an ambiguous result needs to
    name the records it could not choose between.

    A tie returns None on purpose. Answering "we could not tell" is worth more
    than answering with whichever record the registry happened to list first,
    which is how the wrong repository's metadata used to be attached.
    """
    scored = [
        (url_score(catalog_urls, url_of(c), host_matcher), c)
        for c in candidates
    ]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return None, scored
    winners = [c for s, c in scored if s == best]
    return (winners[0] if len(winners) == 1 else None), scored
