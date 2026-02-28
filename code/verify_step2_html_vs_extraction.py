#!/usr/bin/env python3
"""
Verification Step 2: HTML vs extraction consistency.
Samples real HTML files and verifies extractors produce correct output
by cross-referencing with the actual HTML content.
"""
import html as html_module
import json
import random
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from config import PAGES_DIR
from extractors import get_extractor

# Platform directory names -> (extractor key, display name)
PLATFORMS = {
    'glovo': ('glovo', 'Glovo'),
    'justeat': ('justeat', 'Just Eat'),
    'ubereats': ('ubereats', 'Uber Eats'),
}

random.seed(42)


def extract_ground_truth_names_from_html(soup: BeautifulSoup, platform: str) -> list[str]:
    """Try to independently extract restaurant names from HTML for cross-checking."""
    names = []
    # JSON-LD is the most reliable ground truth
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    if item.get('@type') == 'ItemList':
                        for el in item.get('itemListElement', []):
                            if isinstance(el, dict):
                                inner = el.get('item', el)
                                if isinstance(inner, dict) and inner.get('name'):
                                    names.append(inner['name'])
                    elif item.get('name') and item.get('@type') in (
                        'Restaurant', 'FoodEstablishment', 'LocalBusiness', 'Store'
                    ):
                        names.append(item['name'])
        except Exception:
            continue
    return names


def count_initial_state_restaurants(html: str) -> int:
    """Count restaurants in __INITIAL_STATE__ JSON.parse data (Just Eat pages)."""
    state_idx = html.find('__INITIAL_STATE__')
    if state_idx < 0:
        return 0
    marker = 'JSON.parse("'
    parse_idx = html.find(marker, state_idx)
    if parse_idx < 0:
        return 0
    start = parse_idx + len(marker)
    end = html.find('")', start)
    if end < 0:
        return 0  # Truncated
    try:
        decoded = html[start:end].encode('utf-8').decode('unicode_escape')
        decoded = decoded.encode('utf-16', 'surrogatepass').decode('utf-16')
        state = json.loads(decoded)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0
    restaurants = state.get('restaurants', {})
    return len(restaurants) if isinstance(restaurants, dict) else 0


def audit_file(html_path: Path, meta: dict, platform_name: str) -> list[str]:
    """Audit a single file. Returns list of issues found."""
    issues = []

    with open(html_path, 'rb') as f:
        html = f.read().decode('utf-8', errors='replace')

    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string.strip() if soup.title and soup.title.string else ''
    url = meta.get('url', '')

    # Run extractor
    extractor = get_extractor(platform_name)
    restaurants = extractor.extract_restaurants(
        html=html,
        url=url,
        timestamp=meta.get('timestamp', ''),
        crawl_id=meta.get('crawl_id', ''),
    )

    # --- CHECK 1: Very small HTML producing results ---
    if len(html) < 1000 and len(restaurants) > 0:
        issues.append(
            f"SMALL_HTML: {html_path.name} is {len(html)} bytes but extracted "
            f"{len(restaurants)} restaurants"
        )

    # --- CHECK 2: Listing-like URL with 0 results ---
    listing_signals = ['/restaurantes', '/restaurants_', '/restaurants-', '/city/', '/area/']
    is_listing = any(s in url for s in listing_signals)
    if is_listing and len(restaurants) == 0 and len(html) > 5000:
        issues.append(
            f"ZERO_FROM_LISTING: {html_path.name} URL looks like listing ({url[:80]}) "
            f"but 0 restaurants extracted (HTML={len(html)} bytes)"
        )

    # --- CHECK 3: Extracted names vs JSON-LD ground truth ---
    ground_truth = extract_ground_truth_names_from_html(soup, platform_name)
    if ground_truth and restaurants:
        extracted_names = {r.name.lower().strip() for r in restaurants if r.name}
        gt_names = {' '.join(html_module.unescape(n).lower().split()) for n in ground_truth}

        # Check if extracted names are a superset of ground truth (we may extract more from scripts)
        missing = gt_names - extracted_names
        if missing and len(missing) > len(gt_names) * 0.5:
            issues.append(
                f"MISSING_NAMES: {html_path.name} JSON-LD has {len(gt_names)} names, "
                f"extracted {len(extracted_names)}, missing {len(missing)}: "
                f"{list(missing)[:3]}"
            )

    # --- CHECK 4: Suspicious extracted data ---
    for r in restaurants:
        if r.name and len(r.name) > 120:
            issues.append(f"LONG_NAME: '{r.name[:80]}...' in {html_path.name}")
        if r.name and re.search(r'[<>{}]', r.name):
            issues.append(f"HTML_IN_NAME: '{r.name[:60]}' in {html_path.name}")
        if r.city and len(r.city) > 60:
            issues.append(f"LONG_CITY: '{r.city[:40]}...' in {html_path.name}")
        if r.name and r.name.lower() in ('glovo', 'glovoapp', 'just eat', 'uber eats', 'ubereats'):
            issues.append(f"PLATFORM_AS_NAME: '{r.name}' in {html_path.name}")
        if r.name and '&#' in r.name:
            issues.append(f"HTML_ENTITY: '{r.name}' in {html_path.name}")

    # --- CHECK 5: Duplicate names within same extraction ---
    if restaurants:
        name_counts = {}
        for r in restaurants:
            key = (r.name or '').lower()
            name_counts[key] = name_counts.get(key, 0) + 1
        dupes = {k: v for k, v in name_counts.items() if v > 1 and k}
        if dupes:
            total_dupes = sum(v - 1 for v in dupes.values())
            if total_dupes > len(restaurants) * 0.3:
                issues.append(
                    f"INTRA_PAGE_DUPES: {html_path.name} has {total_dupes} duplicate names "
                    f"out of {len(restaurants)} extracted"
                )

    # --- CHECK 6: Embedded state coverage ---
    # Catches cases where a rich data source (e.g. __INITIAL_STATE__) has far
    # more restaurants than the extractor returns.
    state_count = count_initial_state_restaurants(html)
    if state_count > 0 and len(restaurants) < state_count * 0.5:
        issues.append(
            f"LOW_STATE_COVERAGE: {html_path.name} __INITIAL_STATE__ has "
            f"{state_count} restaurants but only {len(restaurants)} extracted "
            f"({len(restaurants) / state_count * 100:.0f}%)"
        )

    return issues


def main():
    print("=" * 70)
    print("STEP 2: HTML vs EXTRACTION CONSISTENCY")
    print("=" * 70)

    all_issues = []
    files_checked = 0
    restaurants_checked = 0

    for dir_name, (extractor_key, display_name) in PLATFORMS.items():
        platform_dir = PAGES_DIR / dir_name
        if not platform_dir.exists():
            print(f"\n  WARNING: {platform_dir} not found!")
            continue

        print(f"\n--- {display_name} ---")

        for crawl_dir in sorted(platform_dir.iterdir()):
            if not crawl_dir.is_dir():
                continue

            html_files = list(crawl_dir.rglob('*.html'))
            if not html_files:
                continue

            # Sample files: pick up to 10 per crawl, biased toward variety
            # Include listing pages AND individual pages
            sample_size = min(10, len(html_files))
            samples = random.sample(html_files, sample_size)

            crawl_issues = []
            crawl_restaurants = 0

            for html_file in samples:
                meta_file = html_file.with_suffix('.json')
                if meta_file.exists():
                    with open(meta_file) as f:
                        meta = json.load(f)
                else:
                    meta = {
                        'platform': extractor_key,
                        'crawl_id': crawl_dir.name,
                        'url': '',
                        'timestamp': '',
                    }

                file_issues = audit_file(html_file, meta, extractor_key)
                crawl_issues.extend(file_issues)
                files_checked += 1

                # Count restaurants for stats
                with open(html_file, 'rb') as f:
                    html = f.read().decode('utf-8', errors='replace')
                extractor = get_extractor(extractor_key)
                rests = extractor.extract_restaurants(
                    html=html,
                    url=meta.get('url', ''),
                    timestamp=meta.get('timestamp', ''),
                    crawl_id=meta.get('crawl_id', crawl_dir.name),
                )
                crawl_restaurants += len(rests)

            status = f"{len(crawl_issues)} issues" if crawl_issues else "OK"
            print(
                f"  {crawl_dir.name}: checked {sample_size}/{len(html_files)} files, "
                f"{crawl_restaurants} restaurants, {status}"
            )

            for issue in crawl_issues:
                print(f"    ! {issue}")

            all_issues.extend(crawl_issues)
            restaurants_checked += crawl_restaurants

    # Summary
    print(f"\n--- SUMMARY ---")
    print(f"Files checked: {files_checked}")
    print(f"Restaurants checked: {restaurants_checked}")

    if all_issues:
        # Categorize issues
        from collections import Counter
        categories = Counter(i.split(':')[0] for i in all_issues)
        print(f"Issues found: {len(all_issues)}")
        for cat, count in categories.most_common():
            print(f"  {cat}: {count}")
    else:
        print("All checks passed!")

    return len(all_issues)


if __name__ == "__main__":
    sys.exit(main())
