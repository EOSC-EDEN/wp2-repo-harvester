#!/usr/bin/env python3
"""
Master Harvest Script - Harvests all repositories from the FIDELIS repos CSV.

Usage:
    python harvest_all.py                    # Harvest all repos
    python harvest_all.py --dry-run          # Show what would be harvested
    python harvest_all.py --limit 5          # Only harvest first 5 repos
    python harvest_all.py --filter pangaea   # Only harvest repos matching 'pangaea'
"""

import json
import csv
import os
import sys
import argparse
from datetime import datetime

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from repo_harvester_server.helper.RepositoryHarvester import RepositoryHarvester
from repo_harvester_server.helper.ServiceInfoHelper import ServiceInfoHelper
from repo_harvester_server.helper.FUSEKIHelper import FUSEKIHelper, FusekiAuthError


# Configuration
CSV_FILE = os.path.join(
    os.path.dirname(__file__),
    'repo_harvester_server',
    'SG4 FIDELIS repos.csv'
)
OUTPUT_DIR = "output"


def load_repositories(csv_path):
    """Load repositories from CSV file."""
    repos = []
    with open(csv_path, mode='r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        for row in reader:
            name = row.get('name', '').strip()
            url = row.get('URL_to_harvest', '').strip()
            fairsharing_id = row.get('FAIRsharing ID', '').strip()
            remarks = row.get('remarks', '').strip()

            if url:  # Only include rows with a URL
                repos.append({
                    'name': name,
                    'url': url,
                    'fairsharing_id': fairsharing_id,
                    'remarks': remarks
                })
    return repos


def make_safe_filename(name):
    """Convert repository name to a safe filename."""
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()
    safe_name = safe_name.replace(' ', '_')
    return safe_name if safe_name else "unnamed_repo"


def harvest_repository(url, name, run_id=None):
    """
    Harvest a single repository.
    Returns (result_dict, stages) where stages holds the per-stage outcome:
    'harvested' (records were exported), 'harmonized' (merged record built)
    and 'persisted' (harmonized graph written to FUSEKI).

    run_id ties this repository's DQV measurements to the batch-wide validation
    run, so all graphs of one harvest share a single prov:Activity.
    """
    harvester = RepositoryHarvester(url, run_id=run_id)
    exported_records = harvester.harvest()

    # Collect all services from all exported records (same logic as controller)
    all_services = []
    for record in exported_records:
        if isinstance(record, dict):
            # Check top-level
            services = record.get("dcat:service", [])
            if isinstance(services, list):
                all_services.extend(services)
            elif services:
                all_services.append(services)

            # Check nested in foaf:primaryTopic
            primary_source = record.get("foaf:primaryTopic", {})
            if isinstance(primary_source, dict):
                nested_services = primary_source.get("dcat:service", [])
                if isinstance(nested_services, list):
                    all_services.extend(nested_services)
                elif nested_services:
                    all_services.append(nested_services)

    # Construct response in same format as API controller
    result = {
        "repoURI": harvester.catalog_url,
        "metadata": exported_records[0] if exported_records else {},
        "services": all_services
    }

    stages = {
        'harvested': bool(exported_records),
        'harmonized': harvester.harmonized_ok,
        'persisted': harvester.persisted_ok,
    }

    return result, stages


def build_summary(total, results, start_time, duration):
    """Build the _harvest_summary.json dict, including per-stage counts."""
    harmonized_count = sum(1 for r in results['success'] if r.get('harmonized'))
    persisted_count = sum(1 for r in results['success'] if r.get('persisted'))
    return {
        'timestamp': start_time.isoformat(),
        'duration_seconds': duration.total_seconds(),
        'total': total,
        'success_count': len(results['success']),
        'failed_count': len(results['failed']),
        'harmonized_count': harmonized_count,
        'persisted_count': persisted_count,
        'success': results['success'],
        'failed': results['failed']
    }


def main():
    parser = argparse.ArgumentParser(
        description='Harvest all FIDELIS repositories from the master CSV.'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be harvested without actually harvesting'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit the number of repositories to harvest'
    )
    parser.add_argument(
        '--filter',
        type=str,
        default=None,
        help='Only harvest repos where name or URL contains this string (case-insensitive)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default=OUTPUT_DIR,
        help=f'Output directory for JSON files (default: {OUTPUT_DIR})'
    )
    parser.add_argument(
        '--csv',
        type=str,
        default=CSV_FILE,
        help=f'Path to CSV file (default: {CSV_FILE})'
    )

    args = parser.parse_args()

    # Load repositories
    try:
        repos = load_repositories(args.csv)
    except FileNotFoundError:
        print(f"Error: CSV file not found at {args.csv}")
        sys.exit(1)

    print(f"Loaded {len(repos)} repositories from CSV")

    # Apply filter if specified
    if args.filter:
        filter_lower = args.filter.lower()
        repos = [
            r for r in repos
            if filter_lower in r['name'].lower() or filter_lower in r['url'].lower()
        ]
        print(f"After filter '{args.filter}': {len(repos)} repositories")

    # Apply limit if specified
    if args.limit:
        repos = repos[:args.limit]
        print(f"Limited to first {args.limit} repositories")

    if not repos:
        print("No repositories to harvest.")
        sys.exit(0)

    # Dry run - just show what would be harvested
    if args.dry_run:
        print("\n--- DRY RUN: Would harvest these repositories ---")
        for i, repo in enumerate(repos, 1):
            print(f"{i:3}. {repo['name']}")
            print(f"     URL: {repo['url']}")
            if repo['remarks']:
                print(f"     Note: {repo['remarks']}")
        print(f"\nTotal: {len(repos)} repositories")
        sys.exit(0)

    # Probe FUSEKI once before any harvesting: catches wrong credentials,
    # which an env-var presence check cannot. A failed probe does NOT stop
    # the run — harvesting works without the store and its results are kept
    # locally — but the run must say up front (and in the verdict) that
    # nothing can be harmonized or persisted.
    fuseki_ok = True
    try:
        FUSEKIHelper().check_connection()
    except FusekiAuthError as e:
        fuseki_ok = False
        print(f"\nWARNING: {e}")
        print("Continuing without FUSEKI: harvest results will be saved locally only.")
        print("Nothing can be harmonised or persisted to the registry store this run.")

    # Create output directory
    output_dir = args.output_dir
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Start harvesting
    start_time = datetime.now()
    # One validation run for the whole batch: every harmonized graph written below
    # points its DQV measurements at this same prov:Activity.
    run_id = ServiceInfoHelper.mint_run_id()
    print(f"\n{'='*60}")
    print(f"FIDELIS Repository Harvest - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Validation run: {run_id}")
    print(f"{'='*60}")

    results = {
        'success': [],
        'failed': [],
        'skipped': []
    }

    for i, repo in enumerate(repos, 1):
        name = repo['name']
        url = repo['url']

        print(f"\n[{i}/{len(repos)}] {name}")
        print(f"    URL: {url}")

        try:
            result, stages = harvest_repository(url, name, run_id=run_id)

            # Save to file
            safe_name = make_safe_filename(name)
            filename = f"{safe_name}.json"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as outfile:
                json.dump(result, outfile, indent=2)

            # Count services found
            service_count = len(result.get('services', []))
            has_metadata = bool(result.get('metadata'))

            print(f"    OK: Saved to {filepath}")
            print(f"        Metadata: {'Yes' if has_metadata else 'No'}, Services: {service_count}")
            print(f"        Harmonized: {'Yes' if stages['harmonized'] else 'NO'}, "
                  f"Persisted to FUSEKI: {'Yes' if stages['persisted'] else 'NO'}")

            results['success'].append({
                'name': name,
                'url': url,
                'file': filepath,
                'services': service_count,
                'harvested': stages['harvested'],
                'harmonized': stages['harmonized'],
                'persisted': stages['persisted']
            })

        except Exception as e:
            print(f"    FAILED: {e}")
            results['failed'].append({
                'name': name,
                'url': url,
                'error': str(e)
            })

    # Summary
    end_time = datetime.now()
    duration = end_time - start_time

    print(f"\n{'='*60}")
    print("HARVEST SUMMARY")
    print(f"{'='*60}")
    print(f"Duration: {duration}")
    print(f"Success:  {len(results['success'])}")
    print(f"Failed:   {len(results['failed'])}")

    if results['failed']:
        print(f"\n--- Failed Repositories ---")
        for item in results['failed']:
            print(f"  - {item['name']}: {item['error']}")

    harmonized = [r for r in results['success'] if r.get('harmonized')]
    not_harmonized = [r for r in results['success'] if not r.get('harmonized')]
    persisted = [r for r in results['success'] if r.get('persisted')]

    print(f"\n{'='*60}")
    print("HARMONISATION SUMMARY")
    print(f"{'='*60}")
    print(f"Harmonized:           {len(harmonized)}")
    print(f"Persisted to FUSEKI:  {len(persisted)}")
    print(f"Not harmonized:       {len(not_harmonized)}")
    if not_harmonized:
        print("\n--- Harvested but NOT harmonized ---")
        for item in not_harmonized:
            print(f"  - {item['name']}")

    # Save summary report
    summary_file = os.path.join(output_dir, '_harvest_summary.json')
    summary = build_summary(len(repos), results, start_time, duration)
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to: {summary_file}")

    print(f"\nOutput directory: {output_dir}")

    # Final verdict: the harvested JSON files are intermediates — the run's
    # end product is the harmonized record in FUSEKI. Say plainly whether it
    # was produced, and give cron/CI a truthful exit code.
    if not persisted:
        print("\nVERDICT: LOCAL ONLY - nothing was persisted to FUSEKI.")
        if not fuseki_ok:
            print("FUSEKI could not be reached with the given credentials, so the harvest")
            print("results were saved locally only and nothing could be harmonised.")
            print("Fix FUSEKI_USERNAME / FUSEKI_PASSWORD and re-run to populate the store.")
        else:
            print("The harvested JSON files in the output directory are intact, but the")
            print("registry store was not updated. Likely cause: wrong or missing")
            print("FUSEKI_USERNAME / FUSEKI_PASSWORD.")
        sys.exit(1)
    elif not_harmonized or results['failed']:
        print(f"\nVERDICT: PARTIAL - {len(persisted)} of {len(repos)} repositories "
              "harmonized and persisted; see the summaries above for the rest.")
    else:
        print(f"\nVERDICT: OK - all {len(persisted)} repositories harvested, "
              "harmonized and persisted.")
    print("Done!")


if __name__ == "__main__":
    main()
