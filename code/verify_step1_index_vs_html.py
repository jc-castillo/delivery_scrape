#!/usr/bin/env python3
"""
Verification Step 1: Index consistency.
Checks that downloaded HTML files are consistent with the Athena index cache.
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from config import PAGES_DIR, INDEX_CACHE_DIR, PLATFORMS

# Map index cache platform keys to pages directory names
PLATFORM_DIR_MAP = {
    'glovo': 'glovo',
    'justeat': 'justeat',
    'ubereats': 'ubereats',
}

PLATFORM_NAME_MAP = {
    'glovo': 'Glovo',
    'justeat': 'Just Eat',
    'ubereats': 'Uber Eats',
}


def count_html_files(platform_dir_name: str, crawl_id: str) -> int:
    """Count HTML files for a platform/crawl combo."""
    crawl_dir = PAGES_DIR / platform_dir_name / crawl_id
    if not crawl_dir.exists():
        return 0
    return sum(1 for _ in crawl_dir.rglob('*.html'))


def count_unique_urls(platform_dir_name: str, crawl_id: str) -> int:
    """Count unique URLs from metadata JSON files."""
    crawl_dir = PAGES_DIR / platform_dir_name / crawl_id
    if not crawl_dir.exists():
        return 0
    urls = set()
    for meta_file in crawl_dir.rglob('*.json'):
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            urls.add(meta.get('url', ''))
        except Exception:
            continue
    return len(urls)


def check_sidecar_integrity(platform_dir_name: str, crawl_id: str) -> tuple[int, int]:
    """Check how many HTML files have a matching JSON sidecar."""
    crawl_dir = PAGES_DIR / platform_dir_name / crawl_id
    if not crawl_dir.exists():
        return 0, 0
    matched = 0
    missing = 0
    for html_file in crawl_dir.rglob('*.html'):
        if html_file.with_suffix('.json').exists():
            matched += 1
        else:
            missing += 1
    return matched, missing


def main():
    print("=" * 70)
    print("STEP 1: INDEX vs DOWNLOADED HTML CONSISTENCY")
    print("=" * 70)

    issues = []

    # Load all index cache files
    index_counts = {}
    for cache_file in sorted(INDEX_CACHE_DIR.glob('*.json')):
        try:
            with open(cache_file) as f:
                records = json.load(f)
            # Parse filename: CC-MAIN-YYYY-WW_platform_athena.json
            name = cache_file.stem  # e.g. CC-MAIN-2024-51_glovo_athena
            parts = name.rsplit('_', 2)
            if len(parts) >= 3:
                crawl_id = parts[0]
                platform_key = parts[1]
                index_counts[(platform_key, crawl_id)] = len(records)
        except Exception as e:
            print(f"  WARNING: Could not read {cache_file}: {e}")
            issues.append(f"Unreadable index cache: {cache_file}")

    # Compare index vs HTML for each combo we have data for
    print(f"\n{'Platform':<12} {'Crawl':<20} {'Index':>8} {'HTML':>8} {'Unique':>8} {'Status'}")
    print("-" * 70)

    total_index = 0
    total_html = 0
    total_unique = 0
    combos_checked = 0

    for platform_key in ['glovo', 'justeat', 'ubereats']:
        dir_name = PLATFORM_DIR_MAP[platform_key]
        crawl_dirs = sorted(
            d.name for d in (PAGES_DIR / dir_name).iterdir()
            if d.is_dir()
        ) if (PAGES_DIR / dir_name).exists() else []

        for crawl_id in crawl_dirs:
            idx_count = index_counts.get((platform_key, crawl_id), None)
            html_count = count_html_files(dir_name, crawl_id)
            unique_count = count_unique_urls(dir_name, crawl_id)

            total_html += html_count
            total_unique += unique_count
            combos_checked += 1

            if idx_count is not None:
                total_index += idx_count

            # Determine status
            if idx_count is None:
                status = "NO INDEX"
                issues.append(f"{platform_key}/{crawl_id}: No index cache file found")
            elif html_count == idx_count:
                status = "OK"
            elif html_count > idx_count:
                dupes = html_count - unique_count
                status = f"+{html_count - idx_count} ({dupes} dupes)"
                if dupes > 0:
                    issues.append(
                        f"{platform_key}/{crawl_id}: {dupes} duplicate HTML files "
                        f"(index={idx_count}, html={html_count}, unique_urls={unique_count})"
                    )
            else:
                status = f"MISSING {idx_count - html_count}"
                issues.append(
                    f"{platform_key}/{crawl_id}: {idx_count - html_count} HTML files missing "
                    f"(index={idx_count}, html={html_count})"
                )

            idx_str = str(idx_count) if idx_count is not None else "N/A"
            print(f"{platform_key:<12} {crawl_id:<20} {idx_str:>8} {html_count:>8} {unique_count:>8} {status}")

    print("-" * 70)
    print(f"{'TOTAL':<12} {'':<20} {total_index:>8} {total_html:>8} {total_unique:>8}")

    # Check sidecar integrity
    print(f"\n--- JSON Sidecar Integrity ---")
    total_matched = 0
    total_missing = 0
    for platform_key in ['glovo', 'justeat', 'ubereats']:
        dir_name = PLATFORM_DIR_MAP[platform_key]
        if not (PAGES_DIR / dir_name).exists():
            continue
        for crawl_dir in sorted((PAGES_DIR / dir_name).iterdir()):
            if not crawl_dir.is_dir():
                continue
            matched, missing = check_sidecar_integrity(dir_name, crawl_dir.name)
            total_matched += matched
            total_missing += missing
            if missing > 0:
                print(f"  {platform_key}/{crawl_dir.name}: {missing} HTML files missing JSON sidecar!")
                issues.append(f"{platform_key}/{crawl_dir.name}: {missing} HTML files without metadata")

    print(f"  Total: {total_matched:,} matched, {total_missing:,} missing sidecars")

    # Summary
    print(f"\n--- SUMMARY ---")
    if issues:
        print(f"Found {len(issues)} issue(s):")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("All checks passed!")

    return len(issues)


if __name__ == "__main__":
    sys.exit(main())
