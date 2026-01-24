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
from cc_index import CommonCrawlIndex
from cc_fetch import CommonCrawlFetcher, filter_listing_urls
from extract_data import extract_all, deduplicate_restaurants, save_to_csv, generate_summary

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_index_step(crawl_ids: list[str], use_api: bool = True) -> Path:
    """
    Step 1: Query Common Crawl index for platform URLs.

    Args:
        crawl_ids: List of crawl IDs to query
        use_api: Whether to use CDX API (True) or direct S3 (False)

    Returns:
        Path to the index results file
    """
    logger.info("="*60)
    logger.info("STEP 1: Querying Common Crawl Index")
    logger.info("="*60)

    cc_index = CommonCrawlIndex()

    all_results = {}
    for crawl_id in crawl_ids:
        logger.info(f"\nProcessing crawl: {crawl_id}")

        # Check cache first
        cached = cc_index.load_index_cache(crawl_id)
        if cached:
            logger.info(f"Using cached results for {crawl_id}")
            all_results[crawl_id] = cached
            continue

        crawl_results = {}
        for platform_key in PLATFORMS:
            logger.info(f"Querying {platform_key}...")
            urls = cc_index.find_platform_urls(platform_key, crawl_id, use_api=use_api)
            crawl_results[platform_key] = urls
            logger.info(f"Found {len(urls)} URLs for {platform_key}")

        all_results[crawl_id] = crawl_results
        cc_index._save_index_cache(crawl_id, crawl_results)

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


def run_fetch_step(index_file: Path, limit: int = None,
                  listings_only: bool = True, max_workers: int = 10) -> int:
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
            # Filter to listing pages if requested
            if listings_only:
                records = filter_listing_urls(records, platform)

            # Add metadata
            for record in records:
                record['crawl_id'] = crawl_id
                record['platform'] = platform

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
    print("\nTop 10 cities:")
    sorted_cities = sorted(summary['by_city'].items(), key=lambda x: -x[1])[:10]
    for city, count in sorted_cities:
        print(f"  {city}: {count}")

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
        "--use-s3",
        action="store_true",
        help="Use direct S3 access instead of CDX API"
    )

    # Fetch step options
    parser.add_argument(
        "--all-pages",
        action="store_true",
        help="Fetch all pages, not just listing pages"
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
    if args.all or args.step == "index":
        index_file = run_index_step(crawl_ids, use_api=not args.use_s3)

    if args.all or args.step == "fetch":
        if args.index_file:
            index_file = Path(args.index_file)
        elif not args.all and not hasattr(locals(), 'index_file'):
            index_file = DATA_DIR / "index_results.json"

        run_fetch_step(
            index_file,
            limit=args.limit,
            listings_only=not args.all_pages,
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
