#!/usr/bin/env python3
"""
Main pipeline script for Common Crawl food delivery scraping.

This script orchestrates the entire pipeline:
1. Query Common Crawl index for platform URLs
2. Download HTML from WARC files
3. Extract restaurant data
4. Save to CSV

Usage:
    # Full pipeline
    python run_pipeline.py --all

    # Individual steps
    python run_pipeline.py --step index
    python run_pipeline.py --step fetch
    python run_pipeline.py --step extract

    # With options
    python run_pipeline.py --all --crawl CC-MAIN-2024-51 --limit 100
"""
import argparse
import json
import logging
import sys
from pathlib import Path

# Add code directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    CC_INDEXES, PLATFORMS, DATA_DIR, PAGES_DIR, OUTPUT_CSV, INDEX_CACHE_DIR
)
from cc_athena import AthenaIndexQuery
from cc_fetch import CommonCrawlFetcher, filter_listing_urls
from extract_data import extract_all, deduplicate_restaurants, save_to_csv, save_per_crawl_platform, generate_summary

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_index_step(crawl_ids: list[str], use_cache: bool = True) -> Path:
    """
    Step 1: Query Common Crawl index for platform URLs using Athena.

    Args:
        crawl_ids: List of crawl IDs to query
        use_cache: Whether to use cached results

    Returns:
        Path to the index results file
    """
    logger.info("="*60)
    logger.info("STEP 1: Querying Common Crawl Index via Athena")
    logger.info("="*60)

    athena = AthenaIndexQuery()

    all_results = {}
    for crawl_id in crawl_ids:
        logger.info(f"\nProcessing crawl: {crawl_id}")

        crawl_results = {}
        for platform_key in PLATFORMS:
            logger.info(f"Querying {platform_key}...")
            urls = athena.query_platform(platform_key, crawl_id, use_cache=use_cache)
            crawl_results[platform_key] = urls
            logger.info(f"Found {len(urls)} URLs for {platform_key}")

        all_results[crawl_id] = crawl_results

    # Save combined results
    output_file = DATA_DIR / "index_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    # Print summary
    total = sum(
        len(urls)
        for crawl in all_results.values()
        for urls in crawl.values()
    )
    logger.info(f"\nTotal URLs found: {total}")
    logger.info(f"Results saved to: {output_file}")

    return output_file


def normalize_athena_record(record: dict) -> dict:
    """
    Normalize Athena record format to match what the fetcher expects.

    Athena returns: warc_filename, warc_record_offset, warc_record_length
    Fetcher expects: filename, offset, length
    """
    return {
        'url': record.get('url', ''),
        'timestamp': record.get('fetch_time', '').replace(' ', 'T').replace('.000', ''),
        'status': record.get('fetch_status', '200'),
        'mime': record.get('content_mime_detected', 'text/html'),
        'filename': record.get('warc_filename', ''),
        'offset': record.get('warc_record_offset', '0'),
        'length': record.get('warc_record_length', '0'),
        'crawl_id': record.get('crawl_id', ''),
        'platform': record.get('platform', ''),
    }


def run_fetch_step(index_file: Path, limit: int = None,
                  listings_only: bool = False, max_workers: int = 10) -> int:
    """
    Step 2: Download HTML from Common Crawl WARC files.

    Args:
        index_file: Path to index results JSON
        limit: Maximum pages per platform per crawl (None = no limit)
        listings_only: Only fetch restaurant listing pages
        max_workers: Number of parallel download workers

    Returns:
        Number of pages downloaded
    """
    logger.info("="*60)
    logger.info("STEP 2: Fetching HTML from Common Crawl")
    logger.info("="*60)

    with open(index_file) as f:
        index_results = json.load(f)

    fetcher = CommonCrawlFetcher()
    total_fetched = 0

    for crawl_id, platforms in index_results.items():
        logger.info(f"\nFetching from: {crawl_id}")

        for platform, records in platforms.items():
            # Normalize Athena records to fetcher format
            records = [normalize_athena_record(r) for r in records]

            # Add metadata
            for record in records:
                record['crawl_id'] = crawl_id
                record['platform'] = platform

            # Filter to listing pages if requested
            if listings_only:
                records = filter_listing_urls(records, platform)

            # Apply limit
            if limit:
                records = records[:limit]

            if not records:
                logger.info(f"No listing pages for {platform}")
                continue

            logger.info(f"Fetching {len(records)} pages for {platform}...")

            # Fetch pages
            warc_records = fetcher.fetch_multiple(records, max_workers=max_workers)

            # Save pages
            for warc_record in warc_records:
                fetcher.save_html(warc_record, PAGES_DIR)

            total_fetched += len(warc_records)
            logger.info(f"Fetched {len(warc_records)} pages for {platform}")

    logger.info(f"\nTotal pages fetched: {total_fetched}")
    return total_fetched


def run_extract_step(pages_dir: Path = PAGES_DIR,
                    output_path: Path = OUTPUT_CSV) -> int:
    """
    Step 3: Extract restaurant data from HTML files.

    Args:
        pages_dir: Directory containing HTML files
        output_path: Path for output CSV

    Returns:
        Number of restaurants extracted
    """
    logger.info("="*60)
    logger.info("STEP 3: Extracting Restaurant Data")
    logger.info("="*60)

    # Extract all restaurants
    restaurants = extract_all(pages_dir)

    if not restaurants:
        logger.warning("No restaurants extracted!")
        return 0

    # Deduplicate
    restaurants = deduplicate_restaurants(restaurants)

    # Save to CSV (combined file)
    save_to_csv(restaurants, output_path)

    # Save per-crawl/platform files (CSV + Parquet)
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
        print(f"  {platform}: {count:,}")

    # Calculate by-crawl stats
    from collections import defaultdict
    by_crawl = defaultdict(lambda: defaultdict(int))
    for rest in restaurants:
        by_crawl[rest.crawl_id][rest.platform] += 1

    print("\nBy crawl and platform:")
    print(f"  {'Crawl':<20} {'Glovo':>10} {'Just Eat':>10} {'Uber Eats':>10} {'Total':>10}")
    print(f"  {'-'*60}")
    for crawl_id in sorted(by_crawl.keys()):
        platforms = by_crawl[crawl_id]
        total = sum(platforms.values())
        print(f"  {crawl_id:<20} {platforms.get('Glovo', 0):>10,} {platforms.get('Just Eat', 0):>10,} {platforms.get('Uber Eats', 0):>10,} {total:>10,}")

    print("\nTop 10 cities:")
    sorted_cities = sorted(summary['by_city'].items(), key=lambda x: -x[1])[:10]
    for city, count in sorted_cities:
        print(f"  {city}: {count:,}")

    print(f"\nOutput files:")
    print(f"  Combined CSV: {output_path}")
    print(f"  Per-crawl files: data/restaurants/")
    print(f"  Summary JSON: {summary_path}")

    return len(restaurants)


def main():
    parser = argparse.ArgumentParser(
        description="Common Crawl Food Delivery Scraping Pipeline"
    )

    # Step selection
    parser.add_argument(
        "--step", "-s",
        choices=["index", "fetch", "extract"],
        help="Run a specific step only"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Run all steps"
    )

    # Common options
    parser.add_argument(
        "--crawl", "-c",
        action="append",
        help="Specific crawl ID(s) to process (can specify multiple)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit pages per platform per crawl"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=10,
        help="Number of parallel workers"
    )

    # Index step options
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't use cached index results"
    )

    # Fetch step options
    parser.add_argument(
        "--listings-only",
        action="store_true",
        help="Only fetch listing pages (default: fetch all pages)"
    )
    parser.add_argument(
        "--index-file", "-i",
        help="Path to existing index results file"
    )

    # Extract step options
    parser.add_argument(
        "--output", "-o",
        default=str(OUTPUT_CSV),
        help="Output CSV file path"
    )

    args = parser.parse_args()

    if not args.step and not args.all:
        parser.print_help()
        print("\nError: Must specify --step or --all")
        sys.exit(1)

    # Determine crawl IDs
    crawl_ids = args.crawl if args.crawl else CC_INDEXES

    # Run pipeline
    index_file = None

    if args.all or args.step == "index":
        index_file = run_index_step(crawl_ids, use_cache=not args.no_cache)

    if args.all or args.step == "fetch":
        if args.index_file:
            index_file = Path(args.index_file)
        elif index_file is None:
            index_file = DATA_DIR / "index_results.json"

        run_fetch_step(
            index_file,
            limit=args.limit,
            listings_only=args.listings_only,
            max_workers=args.workers
        )

    if args.all or args.step == "extract":
        run_extract_step(
            pages_dir=PAGES_DIR,
            output_path=Path(args.output)
        )

    logger.info("\nPipeline complete!")


if __name__ == "__main__":
    main()
