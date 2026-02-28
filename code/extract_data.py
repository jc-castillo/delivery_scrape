"""
Extract restaurant data from downloaded HTML pages.

This module processes HTML files and extracts structured restaurant data,
outputting to a consolidated CSV file and per-crawl/per-platform parquet files.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Iterator
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from config import PAGES_DIR, DATA_DIR, OUTPUT_CSV
from extractors import get_extractor, Restaurant

# Output directory for per-crawl/per-platform files
RESTAURANTS_DIR = DATA_DIR / "restaurants"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def find_html_files(pages_dir: Path = PAGES_DIR) -> Iterator[tuple[Path, dict]]:
    """
    Find all HTML files with their metadata.

    Yields:
        Tuple of (html_path, metadata_dict)
    """
    for html_file in pages_dir.rglob('*.html'):
        meta_file = html_file.with_suffix('.json')
        if meta_file.exists():
            with open(meta_file) as f:
                metadata = json.load(f)
            yield html_file, metadata
        else:
            # Try to infer metadata from path structure
            # Expected: pages/{platform}/{crawl_id}/{timestamp}_{hash}.html
            parts = html_file.relative_to(pages_dir).parts
            if len(parts) >= 2:
                metadata = {
                    'platform': parts[0],
                    'crawl_id': parts[1],
                    'timestamp': html_file.stem.split('_')[0] if '_' in html_file.stem else '',
                    'url': '',
                }
                yield html_file, metadata


def extract_from_file(html_path: Path, metadata: dict) -> list[Restaurant]:
    """
    Extract restaurants from a single HTML file.

    Args:
        html_path: Path to HTML file
        metadata: File metadata dictionary

    Returns:
        List of Restaurant objects
    """
    platform = metadata.get('platform', '')
    if not platform:
        logger.warning(f"No platform in metadata for {html_path}")
        return []

    try:
        extractor = get_extractor(platform)
    except ValueError as e:
        logger.warning(f"Unknown platform {platform}: {e}")
        return []

    try:
        with open(html_path, 'rb') as f:
            html = f.read().decode('utf-8', errors='replace')
    except Exception as e:
        logger.error(f"Error reading {html_path}: {e}")
        return []

    try:
        restaurants = extractor.extract_restaurants(
            html=html,
            url=metadata.get('url', ''),
            timestamp=metadata.get('timestamp', ''),
            crawl_id=metadata.get('crawl_id', ''),
        )
        return restaurants
    except Exception as e:
        logger.error(f"Error extracting from {html_path}: {e}")
        return []


def extract_all(pages_dir: Path = PAGES_DIR,
               max_workers: int = 4) -> list[Restaurant]:
    """
    Extract restaurants from all HTML files.

    Args:
        pages_dir: Directory containing HTML files
        max_workers: Number of parallel workers

    Returns:
        List of all extracted Restaurant objects
    """
    all_restaurants = []
    files = list(find_html_files(pages_dir))

    logger.info(f"Found {len(files)} HTML files to process")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(extract_from_file, path, meta): path
            for path, meta in files
        }

        for i, future in enumerate(as_completed(future_to_file)):
            path = future_to_file[future]
            try:
                restaurants = future.result()
                all_restaurants.extend(restaurants)
                if restaurants:
                    logger.info(
                        f"[{i+1}/{len(files)}] Extracted {len(restaurants)} "
                        f"restaurants from {path.name}"
                    )
            except Exception as e:
                logger.error(f"Error processing {path}: {e}")

    return all_restaurants


def deduplicate_restaurants(restaurants: list[Restaurant]) -> list[Restaurant]:
    """
    Remove duplicate restaurant entries.

    Uses two dedup strategies:
    - Primary: (restaurant_url, crawl_id) when URL is available
    - Fallback: (name, platform, city, crawl_id) for rows without URL

    Uses crawl_id (not date) because pages within the same crawl are archived
    on different days, and the same restaurant can appear on multiple listing
    pages with different timestamps.
    """
    seen_urls = set()
    seen_names = set()
    unique = []

    for rest in restaurants:
        if rest.restaurant_url:
            key = (rest.restaurant_url, rest.crawl_id or '')
            if key not in seen_urls:
                seen_urls.add(key)
                unique.append(rest)
        else:
            key = (
                (rest.name or '').lower(),
                rest.platform or '',
                (rest.city or '').lower(),
                rest.crawl_id or '',
            )
            if key not in seen_names:
                seen_names.add(key)
                unique.append(rest)

    logger.info(f"Deduplicated {len(restaurants)} -> {len(unique)} restaurants")
    return unique


def save_to_csv(restaurants: list[Restaurant], output_path: Path = OUTPUT_CSV):
    """
    Save restaurants to CSV file.

    Args:
        restaurants: List of Restaurant objects
        output_path: Path to output CSV file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = Restaurant.csv_headers()

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()

        for rest in restaurants:
            row = rest.to_dict()
            # Convert list fields to strings
            if isinstance(row.get('categories'), list):
                row['categories'] = '|'.join(row['categories'])
            writer.writerow(row)

    logger.info(f"Saved {len(restaurants)} restaurants to {output_path}")


def save_per_crawl_platform(restaurants: list[Restaurant],
                            output_dir: Path = RESTAURANTS_DIR):
    """
    Save restaurants to separate files per crawl and platform.

    Creates both CSV and Parquet files in the format:
    {output_dir}/{crawl_id}_{platform}.csv
    {output_dir}/{crawl_id}_{platform}.parquet

    Args:
        restaurants: List of Restaurant objects
        output_dir: Directory to save files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group restaurants by crawl_id and platform
    grouped = defaultdict(list)
    for rest in restaurants:
        key = (rest.crawl_id or "unknown", rest.platform or "unknown")
        grouped[key].append(rest)

    logger.info(f"Saving {len(grouped)} crawl/platform combinations to {output_dir}")

    for (crawl_id, platform), rests in grouped.items():
        # Convert to list of dicts
        rows = []
        for rest in rests:
            row = rest.to_dict()
            # Convert list fields to strings for CSV compatibility
            if isinstance(row.get('categories'), list):
                row['categories'] = '|'.join(row['categories'])
            rows.append(row)

        # Create DataFrame
        df = pd.DataFrame(rows)

        # Ensure string columns have consistent types (convert any lists to strings)
        string_columns = ['name', 'platform', 'city', 'date', 'address', 'neighborhood',
                         'food_type', 'categories', 'price_range', 'delivery_fee',
                         'delivery_time', 'min_order', 'restaurant_url', 'image_url',
                         'source_url', 'crawl_id']
        for col in string_columns:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: str(x) if isinstance(x, list) else x)
                df[col] = df[col].astype('string')

        # Generate filename (sanitize crawl_id)
        safe_crawl_id = crawl_id.replace('/', '-')
        base_name = f"{safe_crawl_id}_{platform}"

        # Save as CSV
        csv_path = output_dir / f"{base_name}.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8')

        # Save as Parquet
        parquet_path = output_dir / f"{base_name}.parquet"
        df.to_parquet(parquet_path, index=False, engine='pyarrow')

        logger.info(f"  Saved {len(rests)} restaurants to {base_name}.csv and .parquet")


def generate_summary(restaurants: list[Restaurant]) -> dict:
    """Generate summary statistics from extracted data."""
    from collections import defaultdict

    summary = {
        'total_restaurants': len(restaurants),
        'by_platform': defaultdict(int),
        'by_crawl': defaultdict(int),
        'by_city': defaultdict(int),
        'by_date': defaultdict(int),
        'by_crawl_platform': defaultdict(lambda: defaultdict(int)),
        'by_platform_city': defaultdict(lambda: defaultdict(int)),
    }

    for rest in restaurants:
        summary['by_platform'][rest.platform] += 1
        summary['by_crawl'][rest.crawl_id] += 1
        summary['by_city'][rest.city] += 1
        summary['by_date'][rest.date] += 1
        summary['by_crawl_platform'][rest.crawl_id][rest.platform] += 1
        summary['by_platform_city'][rest.platform][rest.city] += 1

    # Convert defaultdicts to regular dicts for JSON serialization
    summary['by_platform'] = dict(summary['by_platform'])
    summary['by_crawl'] = dict(summary['by_crawl'])
    summary['by_city'] = dict(summary['by_city'])
    summary['by_date'] = dict(summary['by_date'])
    summary['by_crawl_platform'] = {
        k: dict(v) for k, v in summary['by_crawl_platform'].items()
    }
    summary['by_platform_city'] = {
        k: dict(v) for k, v in summary['by_platform_city'].items()
    }

    return summary


def main():
    """Main extraction function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract restaurant data from HTML files"
    )
    parser.add_argument(
        "--pages-dir", "-p",
        default=str(PAGES_DIR),
        help="Directory containing HTML files"
    )
    parser.add_argument(
        "--output", "-o",
        default=str(OUTPUT_CSV),
        help="Output CSV file path"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of parallel workers"
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip deduplication"
    )

    args = parser.parse_args()

    pages_dir = Path(args.pages_dir)
    output_path = Path(args.output)

    # Extract all restaurants
    logger.info("Starting extraction...")
    restaurants = extract_all(pages_dir, max_workers=args.workers)

    if not restaurants:
        logger.warning("No restaurants extracted!")
        return

    # Deduplicate
    if not args.no_dedup:
        restaurants = deduplicate_restaurants(restaurants)

    # Save to CSV (consolidated)
    save_to_csv(restaurants, output_path)

    # Save per crawl/platform files (CSV + Parquet)
    save_per_crawl_platform(restaurants)

    # Generate and save summary
    summary = generate_summary(restaurants)
    summary_path = output_path.with_suffix('.summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    # Print summary
    print("\n" + "="*50)
    print("EXTRACTION SUMMARY")
    print("="*50)
    print(f"Total restaurants: {summary['total_restaurants']}")
    print("\nBy platform:")
    for platform, count in sorted(summary['by_platform'].items()):
        print(f"  {platform}: {count}")
    print("\nBy city (top 10):")
    sorted_cities = sorted(summary['by_city'].items(), key=lambda x: -x[1])[:10]
    for city, count in sorted_cities:
        print(f"  {city}: {count}")
    print("\nBy date (first and last 3):")
    sorted_dates = sorted(summary['by_date'].items())
    for date, count in sorted_dates[:3]:
        print(f"  {date}: {count}")
    if len(sorted_dates) > 6:
        print("  ...")
    for date, count in sorted_dates[-3:]:
        print(f"  {date}: {count}")

    print(f"\nOutput saved to: {output_path}")
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
