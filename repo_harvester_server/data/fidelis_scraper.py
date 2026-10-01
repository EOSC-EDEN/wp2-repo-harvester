"""Sync the FIDELIS network member list into the bulk-harvest CSV.

Safe to run repeatedly. Existing rows keep everything that was curated by hand
(name, URL_to_harvest, FAIRsharing ID, remarks); only "url FIDELIS" and
"FIDELIS member" are maintained here. New members are appended, members that
left the network are flagged False but never deleted.

    python repo_harvester_server/data/fidelis_scraper.py [--dry-run] [--csv PATH]
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://eden-fidelis.eu"
MEMBERS_URL = BASE_URL + "/network-member"
DEFAULT_CSV = Path(__file__).resolve().parent / "SG4 FIDELIS repos.csv"
MEMBER_COL = "FIDELIS member"
FIDELIS_URL_COL = "url FIDELIS"


def find_repo_links(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    hrefs = {str(a['href']) for a in soup.find_all('a', href=True)}
    return sorted(h for h in hrefs if h.startswith('/network-member/'))


def get_repo_info(session, repo_url):
    """Name and homepage from a member page, or (None, None) if either is missing."""
    try:
        response = session.get(repo_url, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {repo_url}: {e}")
        return None, None

    soup = BeautifulSoup(response.content, 'html.parser')

    name_tag = soup.find('h1', class_='page-title')
    name = name_tag.text.strip() if name_tag else None

    url_tag = soup.select_one('a.btn-primary, a.btn-fidelis')
    if not url_tag:
        url_div = soup.find('div', class_='field--name-field-url')
        if url_div:
            url_tag = url_div.find('a')
    url = str(url_tag['href']) if url_tag else None

    return name, url


def scrape_members():
    """All members as (name, url), or None if any page failed.

    A partial list would flip real members to False, so it is all or nothing.
    """
    session = requests.Session()
    try:
        response = session.get(MEMBERS_URL, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {MEMBERS_URL}: {e}")
        return None

    links = find_repo_links(response.content)
    if not links:
        print(f"No member links found on {MEMBERS_URL}; page layout may have changed.")
        return None

    members, failed = [], []
    for link in links:
        name, url = get_repo_info(session, BASE_URL + link)
        if name and url:
            members.append((name, url))
        else:
            failed.append(BASE_URL + link)
    if failed:
        print("Could not extract name and URL from:\n  " + "\n  ".join(failed))
        return None
    return members


def norm_url(url):
    return url.strip().rstrip('/').lower()


def sync(rows, members):
    """Update rows in place. Returns (changes, notes) as printable lines; notes change nothing."""
    changes, notes = [], []
    by_name = {r['name'].strip(): r for r in rows}
    by_url = {norm_url(r[FIDELIS_URL_COL]): r for r in rows if r.get(FIDELIS_URL_COL)}

    matched = set()
    for name, url in members:
        # Name first, then the FIDELIS URL, which catches rows we renamed (e.g. "CLARIN" for "CLARIN ERIC")
        row = by_name.get(name) or by_url.get(norm_url(url))
        if row is None:
            row = {'name': name, 'URL_to_harvest': url, FIDELIS_URL_COL: url,
                   'remarks': f"added from FIDELIS {date.today().isoformat()}; URL_to_harvest not checked"}
            rows.append(row)
            changes.append(f"new member: {name} ({url})")
        elif norm_url(row.get(FIDELIS_URL_COL) or '') != norm_url(url):
            changes.append(f"url FIDELIS changed: {row['name']}: {row.get(FIDELIS_URL_COL) or '(empty)'} -> {url}")
            row[FIDELIS_URL_COL] = url
        if row['name'] != name and id(row) not in matched:
            notes.append(f"note: CSV name '{row['name']}' matched FIDELIS name '{name}' by URL")
        matched.add(id(row))

    for row in rows:
        is_member = id(row) in matched
        old = row.get(MEMBER_COL)
        if old != str(is_member):
            if old == 'True':
                changes.append(f"no longer listed by FIDELIS: {row['name']}")
            elif old == 'False':
                changes.append(f"now a member: {row['name']}")
            row[MEMBER_COL] = str(is_member)
    return changes, notes


def main():
    parser = argparse.ArgumentParser(description="Sync FIDELIS members into the harvest CSV.")
    parser.add_argument('--csv', type=Path, default=DEFAULT_CSV)
    parser.add_argument('--dry-run', action='store_true', help="report changes without writing")
    args = parser.parse_args()

    members = scrape_members()
    if members is None:
        print("Scrape incomplete, CSV left untouched.")
        return 1
    print(f"{len(members)} members listed on {MEMBERS_URL}")

    raw = args.csv.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    with open(args.csv, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if MEMBER_COL not in fieldnames:
        fieldnames.insert(fieldnames.index(FIDELIS_URL_COL) + 1, MEMBER_COL)

    changes, notes = sync(rows, members)
    for line in notes + changes:
        print(line)
    if not changes:
        print("No changes.")
        return 0
    if args.dry_run:
        print("Dry run, CSV not written.")
        return 0

    with open(args.csv, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator=newline)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
