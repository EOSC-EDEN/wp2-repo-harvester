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


def harvest_repository(url, name):
    """
    Harvest a single repository and return results in the standard format.
    Returns (success, result_dict)
    """
    harvester = RepositoryHarvester(url)
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

            # Check nested in prov:hadPrimarySource
            primary_source = record.get("prov:hadPrimarySource", {})
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

    return result


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

    # Create output directory
    output_dir = args.output_dir
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Start harvesting
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f"FIDELIS Repository Harvest - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
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
            result = harvest_repository(url, name)

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

            results['success'].append({
                'name': name,
                'url': url,
                'file': filepath,
                'services': service_count
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

    # Save summary report
    summary_file = os.path.join(output_dir, '_harvest_summary.json')
    summary = {
        'timestamp': start_time.isoformat(),
        'duration_seconds': duration.total_seconds(),
        'total': len(repos),
        'success_count': len(results['success']),
        'failed_count': len(results['failed']),
        'success': results['success'],
        'failed': results['failed']
    }
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to: {summary_file}")

    print(f"\nOutput directory: {output_dir}")
    print("Done!")


if __name__ == "__main__":
    main()
