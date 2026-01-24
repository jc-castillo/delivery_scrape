#!/usr/bin/env python3
"""
Page analysis script - helps understand the structure of platform pages.

This script is used in step 2 to analyze downloaded HTML pages and understand:
1. What type of content each page contains
2. Which pages are listing pages vs individual restaurant pages
3. What data can be extracted from each page type

Usage:
    python analyze_pages.py --pages-dir ../pages --platform glovo
    python analyze_pages.py --sample 5  # Analyze 5 random pages per platform
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from config import PAGES_DIR, PLATFORMS


def analyze_page_structure(html: str) -> dict:
    """Analyze the structure of an HTML page."""
    soup = BeautifulSoup(html, 'html.parser')

    analysis = {
        'title': '',
        'has_json_ld': False,
        'json_ld_types': [],
        'has_next_data': False,
        'has_initial_state': False,
        'num_links': 0,
        'num_cards': 0,
        'key_selectors': [],
        'estimated_type': 'unknown',
    }

    # Page title
    title_tag = soup.find('title')
    if title_tag:
        analysis['title'] = title_tag.get_text().strip()[:100]

    # JSON-LD
    json_ld_scripts = soup.find_all('script', type='application/ld+json')
    if json_ld_scripts:
        analysis['has_json_ld'] = True
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    analysis['json_ld_types'].append(data.get('@type', 'unknown'))
                elif isinstance(data, list):
                    for item in data[:5]:
                        if isinstance(item, dict):
                            analysis['json_ld_types'].append(item.get('@type', 'unknown'))
            except:
                pass

    # Embedded state
    for script in soup.find_all('script'):
        if script.string:
            if '__NEXT_DATA__' in script.string:
                analysis['has_next_data'] = True
            if '__INITIAL_STATE__' in script.string or '__PRELOADED_STATE__' in script.string:
                analysis['has_initial_state'] = True

    # Links
    analysis['num_links'] = len(soup.find_all('a', href=True))

    # Cards/items (potential restaurant cards)
    card_patterns = [
        'article', 'div[class*="card"]', 'div[class*="item"]',
        'div[class*="store"]', 'div[class*="restaurant"]',
        'li[class*="store"]', 'li[class*="restaurant"]',
    ]
    max_cards = 0
    best_selector = None
    for pattern in card_patterns:
        cards = soup.select(pattern)
        if len(cards) > max_cards:
            max_cards = len(cards)
            best_selector = pattern

    analysis['num_cards'] = max_cards
    if best_selector:
        analysis['key_selectors'].append(f"{best_selector} ({max_cards} items)")

    # Estimate page type
    if max_cards > 5:
        analysis['estimated_type'] = 'listing'
    elif max_cards > 0:
        analysis['estimated_type'] = 'detail'
    elif 'restaurant' in analysis['title'].lower() or 'store' in analysis['title'].lower():
        analysis['estimated_type'] = 'detail'
    else:
        analysis['estimated_type'] = 'other'

    return analysis


def analyze_platform_pages(platform: str, pages_dir: Path, sample_size: int = None) -> dict:
    """Analyze all pages for a specific platform."""
    platform_dir = pages_dir / platform

    if not platform_dir.exists():
        print(f"No pages found for {platform}")
        return {}

    results = {
        'platform': platform,
        'total_files': 0,
        'by_crawl': defaultdict(int),
        'page_types': Counter(),
        'json_ld_types': Counter(),
        'has_json_ld': 0,
        'has_embedded_state': 0,
        'sample_analyses': [],
    }

    html_files = list(platform_dir.rglob('*.html'))
    results['total_files'] = len(html_files)

    if sample_size:
        import random
        html_files = random.sample(html_files, min(sample_size, len(html_files)))

    for html_file in html_files:
        # Track crawl distribution
        crawl_id = html_file.parent.name
        results['by_crawl'][crawl_id] += 1

        # Analyze page
        try:
            with open(html_file, 'rb') as f:
                html = f.read().decode('utf-8', errors='replace')

            analysis = analyze_page_structure(html)

            # Update stats
            results['page_types'][analysis['estimated_type']] += 1
            if analysis['has_json_ld']:
                results['has_json_ld'] += 1
            if analysis['has_next_data'] or analysis['has_initial_state']:
                results['has_embedded_state'] += 1
            for jtype in analysis['json_ld_types']:
                results['json_ld_types'][jtype] += 1

            # Store sample for detailed analysis
            if len(results['sample_analyses']) < 10:
                analysis['file'] = str(html_file.relative_to(pages_dir))
                results['sample_analyses'].append(analysis)

        except Exception as e:
            print(f"Error analyzing {html_file}: {e}")

    # Convert counters to dicts
    results['by_crawl'] = dict(results['by_crawl'])
    results['page_types'] = dict(results['page_types'])
    results['json_ld_types'] = dict(results['json_ld_types'])

    return results


def extract_sample_data(html: str, platform: str) -> dict:
    """Try to extract sample restaurant data from a page."""
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from extractors import get_extractor
        extractor = get_extractor(platform)
        restaurants = extractor.extract_restaurants(html, '', '20240101000000', 'test')

        if restaurants:
            return {
                'success': True,
                'count': len(restaurants),
                'sample': restaurants[0].to_dict() if restaurants else None
            }
        return {'success': False, 'count': 0, 'sample': None}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description="Analyze downloaded HTML pages")
    parser.add_argument(
        "--pages-dir", "-d",
        default=str(PAGES_DIR),
        help="Directory containing pages"
    )
    parser.add_argument(
        "--platform", "-p",
        choices=list(PLATFORMS.keys()) + ['all'],
        default='all',
        help="Platform to analyze"
    )
    parser.add_argument(
        "--sample", "-s",
        type=int,
        default=None,
        help="Number of pages to sample per platform"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file for analysis results"
    )
    parser.add_argument(
        "--extract-test",
        action="store_true",
        help="Test extraction on sampled pages"
    )

    args = parser.parse_args()
    pages_dir = Path(args.pages_dir)

    if not pages_dir.exists():
        print(f"Pages directory not found: {pages_dir}")
        sys.exit(1)

    platforms = [args.platform] if args.platform != 'all' else list(PLATFORMS.keys())

    all_results = {}

    for platform in platforms:
        print(f"\n{'='*60}")
        print(f"Analyzing {platform.upper()}")
        print(f"{'='*60}")

        results = analyze_platform_pages(platform, pages_dir, args.sample)

        if not results:
            continue

        all_results[platform] = results

        # Print summary
        print(f"\nTotal files: {results['total_files']}")
        print(f"\nBy crawl:")
        for crawl, count in sorted(results['by_crawl'].items()):
            print(f"  {crawl}: {count}")

        print(f"\nPage types:")
        for ptype, count in results['page_types'].items():
            print(f"  {ptype}: {count}")

        print(f"\nData availability:")
        print(f"  Has JSON-LD: {results['has_json_ld']} ({100*results['has_json_ld']/max(1, len(results.get('sample_analyses', []))):.0f}% of sample)")
        print(f"  Has embedded state: {results['has_embedded_state']}")

        if results['json_ld_types']:
            print(f"\nJSON-LD types:")
            for jtype, count in results['json_ld_types'].items():
                print(f"  {jtype}: {count}")

        # Test extraction
        if args.extract_test and results['sample_analyses']:
            print(f"\nExtraction test:")
            for sample in results['sample_analyses'][:3]:
                filepath = pages_dir / sample['file']
                with open(filepath, 'rb') as f:
                    html = f.read().decode('utf-8', errors='replace')

                extract_result = extract_sample_data(html, platform)
                print(f"  {sample['file'][:50]}...")
                print(f"    Success: {extract_result.get('success', False)}")
                print(f"    Count: {extract_result.get('count', 0)}")
                if extract_result.get('sample'):
                    print(f"    Sample name: {extract_result['sample'].get('name', 'N/A')}")

    # Save results
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
