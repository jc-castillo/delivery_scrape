"""
Extract restaurant data from downloaded HTML pages.

This module processes HTML files and extracts structured restaurant data,
outputting to a consolidated CSV file.
"""
import csv
import json
import logging
from pathlib import Path
from typing import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import PAGES_DIR, DATA_DIR, OUTPUT_CSV
from extractors import get_extractor, Restaurant

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

    Duplicates are identified by: name + platform + city + date
    """
    seen = set()
    unique = []

    for rest in restaurants:
        key = (rest.name.lower(), rest.platform, rest.city.lower(), rest.date)
        if key not in seen:
            seen.add(key)
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


def generate_summary(restaurants: list[Restaurant]) -> dict:
    """Generate summary statistics from extracted data."""
    from collections import defaultdict

    summary = {
        'total_restaurants': len(restaurants),
        'by_platform': defaultdict(int),
        'by_city': defaultdict(int),
        'by_date': defaultdict(int),
        'by_platform_city': defaultdict(lambda: defaultdict(int)),
    }

    for rest in restaurants:
        summary['by_platform'][rest.platform] += 1
        summary['by_city'][rest.city] += 1
        summary['by_date'][rest.date] += 1
        summary['by_platform_city'][rest.platform][rest.city] += 1

    # Convert defaultdicts to regular dicts for JSON serialization
    summary['by_platform'] = dict(summary['by_platform'])
    summary['by_city'] = dict(summary['by_city'])
    summary['by_date'] = dict(summary['by_date'])
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

    # Save to CSV
    save_to_csv(restaurants, output_path)

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
