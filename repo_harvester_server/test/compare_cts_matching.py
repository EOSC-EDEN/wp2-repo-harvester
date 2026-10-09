"""Compare two ways of finding a repository's CoreTrustSeal entry, over the batch CSV.

1. rapidfuzz, as in CoreTrustSealHarvester.harvest() (PR #56, commit c7f5542): the
   exact website, else the most similar cleaned URL (WRatio >= 80), else the most
   similar name (WRatio >= 80, or the CSV name contained in it).
2. UrlMatching.url_score, which the re3data and FAIRsharing harvesters use:
   3 same URL, 2 same host and one path inside the other, 1 same host (or a direct
   subdomain). CoreTrustSeal websites without a scheme get https://, and websites
   are grouped by repository (re3data DOI, else name), so one repository listed
   under two spellings is not a tie. The best score wins, a tie is no match.

With --re3data, every row is also looked up in re3data, and two exact keys say
which CoreTrustSeal repository is the right one: CoreTrustSeal's repository.pid
equal to the repository's re3data DOI, or a re3data certificate URL equal to a
CoreTrustSeal pidUrl. That makes the verdict definite for every row that has a
key, and adds two summary lines for the intended design: the exact key first,
each method only as the fallback where there is no key. Needs the re3data 4.0
parser, so a checkout of master from 2026-10-05 on.

Verdicts: "definitely right" / "definitely wrong" when an exact key confirms or
contradicts a match, "missed" when a key exists but the method found nothing.
Without a key they are a guess: "probably right" when the match is on the batch
URL's own host or carries (almost) the same name, otherwise "probably wrong".

Writes one row per batch repository to a CSV (default output/cts_matching.csv):
what each method compared, the score, what it found and the verdict. The row
below the header says what each column answers. Prints the totals. Run from the repository root:

    pip install rapidfuzz
    python repo_harvester_server/test/compare_cts_matching.py [--re3data] [--csv PATH]
"""
import argparse
import csv
import os
import re
import sys
from collections import Counter
from urllib.parse import urlparse

import requests
from rapidfuzz import fuzz, process

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from repo_harvester_server.helper import UrlMatching

CSV_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'SG4 FIDELIS repos.csv')
DEFAULT_OUT = os.path.join('output', 'cts_matching.csv')
GRAPHQL = 'https://backend.amt.coretrustseal.org/graphql'
QUERY = '{ certificates { certificationRequest { pidUrl repository { id name website pid } } } }'
DOI = re.compile(r'10\.\d{4,9}/[^\s"<>&?#]+')
COLUMNS = [
    'batch_name', 'batch_url',
    'exact_key', 'exact_cts_name', 'exact_cts_website',
    'rf_step', 'rf_compared', 'rf_against', 'rf_score', 'rf_cts_name', 'rf_cts_website', 'rf_same_host',
    'rf_verdict',
    'um_score', 'um_note', 'um_cts_name', 'um_cts_website', 'um_verdict',
    'key_rf_cts_name', 'key_rf_by', 'key_rf_verdict',
    'key_um_cts_name', 'key_um_by', 'key_um_verdict',
]
# Second row of the CSV: the question each column answers.
DESCRIPTIONS = {
    'batch_name': 'Which repository from the batch CSV (column "name") is this row about?',
    'batch_url': 'Which URL from the batch CSV (URL_to_harvest) was matched against CoreTrustSeal?',
    'exact_key': 'Which exact key, if any, found the right CoreTrustSeal entry: repository.pid = re3data DOI, '
                 'or the re3data certificate DOI? Empty without --re3data.',
    'exact_cts_name': 'Which CoreTrustSeal repository does the exact key point to, i.e. the right answer?',
    'exact_cts_website': 'Which website does CoreTrustSeal list for that right repository?',
    'rf_step': 'Which step decided the rapidfuzz match: exact website, URL, name, or none?',
    'rf_compared': 'What did rapidfuzz compare: the cleaned batch URL, or the batch name in the name step?',
    'rf_against': 'Which CoreTrustSeal value (cleaned website or name) came out most similar? '
                  'Without an accepted match: the nearest website.',
    'rf_score': 'How similar were the two (WRatio from 0 to 100, accepted from 80)?',
    'rf_cts_name': 'Which CoreTrustSeal repository did rapidfuzz match, if any?',
    'rf_cts_website': 'Which website does CoreTrustSeal list for the rapidfuzz match?',
    'rf_same_host': 'Is that website on the same host as the batch URL (ignoring www.)?',
    'rf_verdict': 'How good is the rapidfuzz match? "definitely right/wrong" by the exact key, '
                  '"missed" if a key exists but nothing matched. Without a key a guess: "probably right" '
                  'if on the batch URL\'s host or (almost) the same name, else "probably wrong".',
    'um_score': 'Which UrlMatching score did the best CoreTrustSeal website get? 3 same URL, '
                '2 same host and one path inside the other, 1 same host or direct subdomain, 0 nothing.',
    'um_note': 'Why did UrlMatching not match: a tie between repositories, or no host in common?',
    'um_cts_name': 'Which CoreTrustSeal repository did UrlMatching match, if any?',
    'um_cts_website': 'Which CoreTrustSeal website scored best? On a tie, all of them, separated by |.',
    'um_verdict': 'How good is the UrlMatching match? Same levels as rf_verdict.',
    'key_rf_cts_name': 'Exact key first, rapidfuzz only without a key: which CoreTrustSeal repository '
                       'does that end up with? Empty without --re3data.',
    'key_rf_by': 'Who decided there: the exact key, or rapidfuzz as the fallback?',
    'key_rf_verdict': 'How good is that result? "definitely right" where the key decides, '
                      'otherwise the rapidfuzz verdict.',
    'key_um_cts_name': 'Exact key first, UrlMatching only without a key: which CoreTrustSeal repository '
                       'does that end up with? Empty without --re3data.',
    'key_um_by': 'Who decided there: the exact key, or UrlMatching as the fallback?',
    'key_um_verdict': 'How good is that result? "definitely right" where the key decides, '
                      'otherwise the UrlMatching verdict.',
}


def doi_of(value):
    match = DOI.search(value or '')
    return match.group().lower() if match else None


def load_cts():
    response = requests.post(GRAPHQL, json={'query': QUERY}, timeout=60,
                             headers={'User-Agent': 'EDEN harvester matching check'})
    response.raise_for_status()
    cert_requests = [c['certificationRequest'] for c in response.json()['data']['certificates']]
    repos = {r['repository']['id']: r['repository'] for r in cert_requests}
    by_cert_doi = {doi_of(r['pidUrl']): r['repository']['id'] for r in cert_requests}
    return repos, by_cert_doi


def rapidfuzz_match(url, name, websites, names):
    """Mirrors CoreTrustSealHarvester.harvest(): exact website, then URL, then name.
    Returns (repository id or None, step, compared, against, score)."""
    def clean_url(u):
        parsed = urlparse(u.lower().strip())
        return f"{parsed.netloc.replace('www.', '')}{parsed.path.rstrip('/')}"

    if url in websites:
        return websites[url], 'exact website', url, url, 100
    choices = {clean_url(u): u for u in websites}
    best = process.extractOne(clean_url(url), choices.keys(), scorer=fuzz.WRatio)
    if best and best[1] >= 80:
        return websites[choices[best[0]]], 'URL', clean_url(url), best[0], round(best[1])
    nearest_url = (clean_url(url), best[0] if best else '', round(best[1]) if best else '')
    best = process.extractOne(name, names.keys(), scorer=fuzz.WRatio)
    if best and (best[1] >= 80 or name in best[0]):
        return names[best[0]], 'name', name, best[0], round(best[1])
    # Nothing accepted: show the URL that came nearest, so the row says how near.
    return (None, 'none', *nearest_url)


def urlmatching_match(url, websites, repos):
    """Returns (repository id or None, score, website, note)."""
    best_per_repo = {}
    for site, repo_id in websites.items():
        score = UrlMatching.url_score([url], site if '://' in site else 'https://' + site)
        key = repository_key(repos[repo_id])
        if score > best_per_repo.get(key, (0,))[0]:
            best_per_repo[key] = (score, site, repo_id)
    if not best_per_repo:
        return None, 0, '', 'no host in common'
    best = max(entry[0] for entry in best_per_repo.values())
    winners = [entry for entry in best_per_repo.values() if entry[0] == best]
    if len(winners) > 1:
        sites = ' | '.join(site for _, site, _ in winners)
        return None, best, sites, f'tie between {len(winners)} repositories'
    score, site, repo_id = winners[0]
    return repo_id, score, site, ''


def exact_match(url, name, harvester, by_pid, by_cert_doi):
    try:
        record = harvester.harvest(url, name) or {}
    except Exception as e:
        # a registry hiccup leaves this row unverified, it says nothing about matching
        return None, f're3data unavailable: {type(e).__name__}'
    re3data_doi = next((doi_of(i) for i in record.get('identifier', []) if '10.17616/' in i), None)
    if re3data_doi in by_pid:
        return by_pid[re3data_doi], 'repository.pid = re3data DOI'
    for cert in record.get('certificates') or []:
        if doi_of(cert.get('url')) in by_cert_doi:
            return by_cert_doi[doi_of(cert.get('url'))], 're3data certificate DOI'
    return None, 'no exact key'


VERDICTS = ['definitely right', 'probably right', 'probably wrong', 'definitely wrong', 'missed']


def same_host(url, website):
    """Same host, ignoring www. Stricter than UrlMatching's direct-subdomain rule on
    purpose: ISSDA (ucd.ie) to the UCD Digital Library (digital.ucd.ie) is wrong."""
    def host(u):
        return UrlMatching.normalize_hostname(urlparse(u if '://' in u else 'https://' + u).hostname)
    return host(url) == host(website)


def repository_key(repo):
    """CoreTrustSeal sometimes files a renewal under a new repository.id (4TU: 130
    and 343), so a repository is its re3data DOI, else its name."""
    return doi_of(repo.get('pid')) or repo['name'].strip().casefold()


def same_repository(a, b, repos):
    ra, rb = repos[a], repos[b]
    return (a == b or repository_key(ra) == repository_key(rb)
            or ra['name'].strip().casefold() == rb['name'].strip().casefold())


def verdict(found, exact, url, name, repos):
    if exact is not None:
        if found is None:
            return 'missed'
        return 'definitely right' if same_repository(found, exact, repos) else 'definitely wrong'
    if found is None:
        return ''
    # DataverseNO sits on another host than its batch URL but has the same name;
    # STRING Database ~ TOAR Database Infrastructure has neither.
    same_name = fuzz.ratio(name.casefold(), repos[found]['name'].casefold()) >= 90
    return 'probably right' if same_host(url, repos[found]['website']) or same_name else 'probably wrong'


def key_first(exact, found, found_verdict, label):
    """The intended design: an exact key decides where there is one, the method
    only fills in the rows without. Returns (repository id or None, by, verdict)."""
    if exact is not None:
        return exact, 'exact key', 'definitely right'
    if found is not None:
        return found, label, found_verdict
    return None, '', ''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--re3data', action='store_true',
                        help='decide right/wrong with the exact keys, and show them used first')
    parser.add_argument('--csv', default=DEFAULT_OUT, help=f'where the table goes (default: {DEFAULT_OUT})')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    repos, by_cert_doi = load_cts()
    websites, names = {}, {}
    for repo_id, repo in repos.items():
        websites.setdefault(repo['website'], repo_id)
        names.setdefault(repo['name'], repo_id)
    by_pid = {doi_of(r.get('pid')): repo_id for repo_id, r in repos.items() if doi_of(r.get('pid'))}

    harvester = None
    if args.re3data:
        from repo_harvester_server.helper.Re3DataHarvester import Re3DataHarvester
        harvester = Re3DataHarvester()
        if 'v40' not in harvester.api_url:
            sys.exit('--re3data needs the re3data 4.0 parser: update to current master first.')

    with open(CSV_PATH, encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['URL_to_harvest']]

    def cts(repo_id, field):
        return repos[repo_id][field] if repo_id else ''

    table = []
    for row in rows:
        url, name = row['URL_to_harvest'], row['name']
        rf_id, rf_step, rf_compared, rf_against, rf_score = rapidfuzz_match(url, name, websites, names)
        um_id, um_score, um_site, um_note = urlmatching_match(url, websites, repos)
        exact, exact_how = exact_match(url, name, harvester, by_pid, by_cert_doi) if harvester else (None, '')
        rf_verdict = verdict(rf_id, exact, url, name, repos)
        um_verdict = verdict(um_id, exact, url, name, repos)
        entry = {
            'batch_name': name, 'batch_url': url,
            'exact_key': exact_how, 'exact_cts_name': cts(exact, 'name'), 'exact_cts_website': cts(exact, 'website'),
            'rf_step': rf_step, 'rf_compared': rf_compared, 'rf_against': rf_against, 'rf_score': rf_score,
            'rf_cts_name': cts(rf_id, 'name'), 'rf_cts_website': cts(rf_id, 'website'),
            'rf_same_host': ('yes' if same_host(url, cts(rf_id, 'website')) else 'no') if rf_id else '',
            'rf_verdict': rf_verdict,
            'um_score': um_score, 'um_note': um_note, 'um_cts_name': cts(um_id, 'name'),
            'um_cts_website': um_site, 'um_verdict': um_verdict,
        }
        if harvester:
            for prefix, found, found_verdict, label in (('key_rf', rf_id, rf_verdict, 'rapidfuzz'),
                                                        ('key_um', um_id, um_verdict, 'UrlMatching')):
                repo_id, by, v = key_first(exact, found, found_verdict, label)
                entry.update({f'{prefix}_cts_name': cts(repo_id, 'name'), f'{prefix}_by': by,
                              f'{prefix}_verdict': v})
        table.append(entry)

    os.makedirs(os.path.dirname(args.csv) or '.', exist_ok=True)
    # utf-8-sig so a spreadsheet keeps the accents in CoreTrustSeal's names
    with open(args.csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(DESCRIPTIONS)
        writer.writerows(table)

    print(f'{len(table)} batch URLs against {len(repos)} CoreTrustSeal repositories -> {args.csv}')
    methods = (('rf', 'rapidfuzz'), ('um', 'UrlMatching'))
    keyed = sum(1 for t in table if t['exact_cts_name'])
    if harvester:
        print(f'{keyed} of them have an exact key')
    for prefix, label in methods:
        counts = Counter(t[f'{prefix}_verdict'] for t in table)
        matched = sum(1 for t in table if t[f'{prefix}_cts_name'])
        print(f'{label}: matched {matched} | ' + ', '.join(f'{v} {counts[v]}' for v in VERDICTS))

    if harvester:
        print()
        for prefix, label in methods:
            counts = Counter(t[f'key_{prefix}_verdict'] for t in table)
            matched = sum(1 for t in table if t[f'key_{prefix}_cts_name'])
            print(f'exact key first, then {label}: matched {matched} | '
                  + ', '.join(f'{v} {counts[v]}' for v in VERDICTS if v != 'missed'))


if __name__ == '__main__':
    main()
