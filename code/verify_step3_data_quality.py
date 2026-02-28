#!/usr/bin/env python3
"""
Verification Step 3: Data quality and extractor robustness.
Deep-checks the extracted CSV and audits extractor code against real HTML patterns.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from config import PAGES_DIR, DATA_DIR, OUTPUT_CSV

PLATFORM_DIR_MAP = {'Glovo': 'glovo', 'Just Eat': 'justeat', 'Uber Eats': 'ubereats'}


def check_csv_quality(df: pd.DataFrame) -> list[str]:
    """Check the extracted CSV for data quality issues."""
    issues = []

    print("--- A. CSV Data Quality ---")

    # 1. HTML entities
    html_ent = df[df['name'].str.contains('&#', na=False)]
    print(f"  Names with HTML entities: {len(html_ent)}")
    if len(html_ent) > 0:
        issues.append(f"HTML_ENTITIES: {len(html_ent)} names still contain HTML entities")
        print(f"    Examples: {html_ent['name'].head(3).tolist()}")

    # 2. Very short names
    short = df[df['name'].str.len() <= 2]
    print(f"  Names <= 2 chars: {len(short)}")
    if len(short) > 0:
        print(f"    Values: {short['name'].value_counts().to_dict()}")

    # 3. Very long names
    long_names = df[df['name'].str.len() > 100]
    print(f"  Names > 100 chars: {len(long_names)}")
    if len(long_names) > 0:
        issues.append(f"LONG_NAMES: {len(long_names)} names exceed 100 chars")
        for n in long_names['name'].head(3):
            print(f"    '{n[:100]}...'")

    # 4. Names with HTML/JS artifacts
    bad_chars = df[df['name'].str.contains(r'[<>{}]', na=False, regex=True)]
    print(f"  Names with <>{{}}: {len(bad_chars)}")
    if len(bad_chars) > 0:
        issues.append(f"HTML_ARTIFACTS: {len(bad_chars)} names contain HTML/JS characters")

    # 5. Platform names as restaurant names
    for plat in ['Glovo', 'Just Eat', 'Uber Eats', 'UberEats', 'GlovoApp']:
        matches = df[df['name'].str.lower() == plat.lower()]
        if len(matches) > 0:
            issues.append(f"PLATFORM_NAME: '{plat}' appears as restaurant name {len(matches)} times")
            print(f"  '{plat}' as restaurant name: {len(matches)}")

    # 6. Duplicate URL+crawl_id
    has_url = df[df['restaurant_url'].notna() & (df['restaurant_url'] != '')]
    url_dupes = has_url[has_url.duplicated(subset=['restaurant_url', 'crawl_id'], keep=False)]
    print(f"  Duplicate URL+crawl_id: {len(url_dupes)}")
    if len(url_dupes) > 0:
        issues.append(f"URL_DUPES: {len(url_dupes)} rows share restaurant_url+crawl_id")

    # 7. Empty/null city
    empty_city = (df['city'] == '').sum() + df['city'].isna().sum()
    print(f"  Empty city: {empty_city:,} ({empty_city/len(df)*100:.1f}%)")

    # 8. Glovo bad city values
    glovo = df[df['platform'] == 'Glovo']
    bad_cities = glovo[glovo['city'].str.lower().str.contains(
        'domicilio|delivery|glovo|banaketa', na=False
    )]
    print(f"  Glovo non-city values: {len(bad_cities)}")
    if len(bad_cities) > 0:
        issues.append(f"BAD_CITIES: {len(bad_cities)} Glovo rows have non-city values")

    # 9. Just Eat corrupted cities
    je = df[df['platform'] == 'Just Eat']
    je_bad = je[je['city'].str.startswith('Restaurants', na=False)]
    print(f"  Just Eat 'Restaurants...' cities: {len(je_bad)}")
    if len(je_bad) > 0:
        issues.append(f"JE_CORRUPTED_CITY: {len(je_bad)} Just Eat rows have 'Restaurants...' as city")

    # 10. Uber Eats URL-encoded cities
    ue = df[df['platform'] == 'Uber Eats']
    ue_pct = ue[ue['city'].str.contains('%', na=False)]
    print(f"  Uber Eats %-encoded cities: {len(ue_pct)}")
    if len(ue_pct) > 0:
        issues.append(f"UE_ENCODED_CITY: {len(ue_pct)} Uber Eats rows have %-encoded cities")

    # 11. Uber Eats ", Spain" suffix
    ue_spain = ue[ue['city'].str.contains(', Spain', na=False)]
    print(f"  Uber Eats ', Spain' cities: {len(ue_spain)}")
    if len(ue_spain) > 0:
        issues.append(f"UE_SPAIN_SUFFIX: {len(ue_spain)} Uber Eats rows have ', Spain' in city")

    return issues


def check_food_type_coverage(df: pd.DataFrame) -> list[str]:
    """Check food_type fill rates."""
    issues = []

    print("\n--- B. Food Type Coverage ---")

    for platform in ['Glovo', 'Just Eat', 'Uber Eats']:
        plat_df = df[df['platform'] == platform]
        for crawl_id in sorted(plat_df['crawl_id'].unique()):
            crawl_df = plat_df[plat_df['crawl_id'] == crawl_id]
            fill = crawl_df['food_type'].notna().mean() * 100
            filled = crawl_df['food_type'].notna().sum()
            total = len(crawl_df)
            status = "OK" if fill > 10 else "LOW"
            print(f"  {platform:<12} {crawl_id:<20} {fill:5.1f}% ({filled:>6}/{total:>6}) {status}")

    return issues


def check_url_patterns(df: pd.DataFrame) -> list[str]:
    """Check that extracted URLs look reasonable."""
    issues = []

    print("\n--- C. Restaurant URL Patterns ---")

    for platform in ['Glovo', 'Just Eat', 'Uber Eats']:
        plat_df = df[df['platform'] == platform]
        has_url = plat_df['restaurant_url'].notna() & (plat_df['restaurant_url'] != '')
        url_pct = has_url.mean() * 100
        print(f"  {platform}: {url_pct:.1f}% have restaurant_url")

        # Check URL domains
        urls = plat_df.loc[has_url, 'restaurant_url']
        domain_counts = Counter()
        for url in urls.head(1000):
            match = re.search(r'https?://([^/]+)', str(url))
            if match:
                domain_counts[match.group(1)] += 1
            else:
                domain_counts['NO_DOMAIN'] += 1

        for domain, count in domain_counts.most_common(5):
            print(f"    {domain}: {count}")

        # Check for unexpected domains
        expected = {
            'Glovo': ['glovoapp.com'],
            'Just Eat': ['www.just-eat.es', 'just-eat.es'],
            'Uber Eats': ['www.ubereats.com', 'ubereats.com'],
        }
        for domain, count in domain_counts.items():
            if domain != 'NO_DOMAIN' and not any(
                domain.endswith(exp) for exp in expected.get(platform, [])
            ):
                issues.append(
                    f"UNEXPECTED_DOMAIN: {platform} has {count} URLs with domain '{domain}'"
                )

    return issues


def check_json_ld_types() -> list[str]:
    """Check JSON-LD @type distribution across platforms to verify we're not missing types."""
    issues = []

    print("\n--- D. JSON-LD @type Distribution (sampled from HTML) ---")

    for platform_name, dir_name in PLATFORM_DIR_MAP.items():
        platform_dir = PAGES_DIR / dir_name
        if not platform_dir.exists():
            continue

        type_counter = Counter()
        files_checked = 0
        for crawl_dir in sorted(platform_dir.iterdir()):
            if not crawl_dir.is_dir():
                continue
            html_files = list(crawl_dir.rglob('*.html'))[:100]
            for hf in html_files:
                files_checked += 1
                try:
                    with open(hf, 'rb') as f:
                        content = f.read().decode('utf-8', errors='replace')
                    soup = BeautifulSoup(content, 'html.parser')
                    for script in soup.find_all('script', type='application/ld+json'):
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            type_counter[data.get('@type', 'NO_TYPE')] += 1
                        elif isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict):
                                    type_counter[item.get('@type', 'NO_TYPE')] += 1
                except Exception:
                    continue

        print(f"  {platform_name} ({files_checked} files sampled):")
        for t, c in type_counter.most_common(10):
            # Flag types we might be ignoring
            handled = {
                'Restaurant', 'LocalBusiness', 'FoodEstablishment', 'FoodService',
                'Store', 'ItemList', 'SearchResultsPage', 'ListItem',
                'WebSite', 'WebPage', 'BreadcrumbList', 'Organization',
            }
            flag = " <-- NOT HANDLED" if t not in handled and c > 5 else ""
            print(f"    {t}: {c}{flag}")

    return issues


def check_glovo_url_patterns() -> list[str]:
    """Check what Glovo URL patterns exist and whether our food_type regex catches them."""
    issues = []

    print("\n--- E. Glovo URL Pattern Analysis ---")

    glovo_dir = PAGES_DIR / 'glovo'
    if not glovo_dir.exists():
        print("  Glovo directory not found!")
        return issues

    has_food_type = 0
    no_food_type = 0
    unmatched_patterns = Counter()

    for crawl_dir in sorted(glovo_dir.iterdir()):
        if not crawl_dir.is_dir():
            continue
        for meta_file in list(crawl_dir.rglob('*.json'))[:500]:
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                url = meta.get('url', '')
            except Exception:
                continue

            cat_match = re.search(
                r'/(?:restaurantes|restaurants|menjar|comida)[^/]*/([^/]+)', url
            )
            if cat_match:
                has_food_type += 1
            else:
                no_food_type += 1
                # Categorize what patterns we're NOT matching
                path_match = re.search(r'glovoapp\.com/es/[^/]+/[^/]+/([^/\?]+)', url)
                if path_match:
                    segment = path_match.group(1)
                    # Normalize: strip numeric suffixes
                    segment = re.sub(r'_\d+$', '', segment)
                    # Only track listing-like segments
                    if not re.match(r'^[a-z]', segment):
                        continue
                    unmatched_patterns[segment] += 1

    total = has_food_type + no_food_type
    print(f"  URLs with food_type from URL: {has_food_type}/{total} ({has_food_type/total*100:.1f}%)")
    print(f"  URLs without food_type from URL: {no_food_type}/{total}")
    print(f"  Unmatched listing-like URL segments:")
    for pat, cnt in unmatched_patterns.most_common(20):
        # Flag patterns that look like food categories we should be matching
        food_like = any(
            x in pat.lower()
            for x in ['food', 'menjar', 'comida', 'restaur', 'cocina', 'cuina']
        )
        flag = " <-- POTENTIAL FOOD CATEGORY" if food_like else ""
        print(f"    {pat}: {cnt}{flag}")

    return issues


def check_next_data_coverage() -> list[str]:
    """Check __NEXT_DATA__ presence in Just Eat pages."""
    issues = []

    print("\n--- F. Just Eat __NEXT_DATA__ Coverage ---")

    je_dir = PAGES_DIR / 'justeat'
    if not je_dir.exists():
        return issues

    for crawl_dir in sorted(je_dir.iterdir()):
        if not crawl_dir.is_dir():
            continue
        with_next = 0
        without_next = 0
        total_checked = 0
        for hf in list(crawl_dir.rglob('*.html'))[:200]:
            total_checked += 1
            with open(hf, 'rb') as f:
                # Only read first 50KB to check for script tag
                content = f.read(50000).decode('utf-8', errors='replace')
            if '__NEXT_DATA__' in content:
                with_next += 1
            else:
                without_next += 1

        print(
            f"  {crawl_dir.name}: {with_next} with __NEXT_DATA__, "
            f"{without_next} without (of {total_checked} checked)"
        )

    return issues


def main():
    print("=" * 70)
    print("STEP 3: DATA QUALITY & EXTRACTOR ROBUSTNESS")
    print("=" * 70)

    # Load CSV
    df = pd.read_csv(OUTPUT_CSV, low_memory=False)
    print(f"Loaded {len(df):,} rows from {OUTPUT_CSV}\n")

    all_issues = []

    all_issues.extend(check_csv_quality(df))
    all_issues.extend(check_food_type_coverage(df))
    all_issues.extend(check_url_patterns(df))
    all_issues.extend(check_json_ld_types())
    all_issues.extend(check_glovo_url_patterns())
    all_issues.extend(check_next_data_coverage())

    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    if all_issues:
        print(f"Found {len(all_issues)} issue(s):")
        for issue in all_issues:
            print(f"  - {issue}")
    else:
        print("All checks passed!")

    return len(all_issues)


if __name__ == "__main__":
    sys.exit(main())
