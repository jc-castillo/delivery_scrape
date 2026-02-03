#!/usr/bin/env python3
"""
Deduplicate restaurant data by name + platform + city + crawl_id.

This script removes duplicate entries where the same restaurant appears
multiple times within the same crawl (e.g., from both listing pages and
individual restaurant pages).
"""
import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from config import DATA_DIR, OUTPUT_CSV

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Output directory for per-crawl/per-platform files
RESTAURANTS_DIR = DATA_DIR / "restaurants"


def deduplicate_csv(input_path: Path, output_path: Path = None) -> pd.DataFrame:
    """
    Deduplicate restaurants by name + platform + city + crawl_id.

    Args:
        input_path: Path to input CSV
        output_path: Path to output CSV (default: overwrites input)

    Returns:
        Deduplicated DataFrame
    """
    if output_path is None:
        output_path = input_path

    logger.info(f"Loading {input_path}")
    df = pd.read_csv(input_path, low_memory=False)

    original_count = len(df)
    logger.info(f"Original row count: {original_count:,}")

    # Normalize name and city for comparison (lowercase, strip whitespace)
    df['_name_norm'] = df['name'].fillna('').str.lower().str.strip()
    df['_city_norm'] = df['city'].fillna('').str.lower().str.strip()

    # Dedup by name + platform + city + crawl_id
    # Keep first occurrence (arbitrary, could also keep one with most data)
    dedup_cols = ['_name_norm', 'platform', '_city_norm', 'crawl_id']
    df_dedup = df.drop_duplicates(subset=dedup_cols, keep='first')

    # Remove temp columns
    df_dedup = df_dedup.drop(columns=['_name_norm', '_city_norm'])

    dedup_count = len(df_dedup)
    removed = original_count - dedup_count

    logger.info(f"After deduplication: {dedup_count:,} rows ({removed:,} duplicates removed)")

    # Save
    df_dedup.to_csv(output_path, index=False)
    logger.info(f"Saved to {output_path}")

    return df_dedup


def regenerate_per_crawl_files(df: pd.DataFrame, output_dir: Path = RESTAURANTS_DIR):
    """
    Regenerate per-crawl/platform CSV and Parquet files from deduplicated data.

    Args:
        df: Deduplicated DataFrame
        output_dir: Directory to save files
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Group by crawl_id and platform
    for (crawl_id, platform), group_df in df.groupby(['crawl_id', 'platform']):
        # Sanitize crawl_id for filename
        safe_crawl_id = crawl_id.replace('/', '-')
        base_name = f"{safe_crawl_id}_{platform}"

        # Save CSV
        csv_path = output_dir / f"{base_name}.csv"
        group_df.to_csv(csv_path, index=False)

        # Save Parquet
        parquet_path = output_dir / f"{base_name}.parquet"
        group_df.to_parquet(parquet_path, index=False, engine='pyarrow')

        logger.info(f"  Saved {len(group_df):,} restaurants to {base_name}")


def generate_summary(df: pd.DataFrame) -> dict:
    """Generate summary statistics from DataFrame."""
    summary = {
        'total_restaurants': len(df),
        'by_platform': df['platform'].value_counts().to_dict(),
        'by_crawl': df['crawl_id'].value_counts().to_dict(),
        'by_city': df['city'].value_counts().to_dict(),
        'by_crawl_platform': {},
    }

    # By crawl and platform
    for crawl_id in df['crawl_id'].unique():
        crawl_df = df[df['crawl_id'] == crawl_id]
        summary['by_crawl_platform'][crawl_id] = crawl_df['platform'].value_counts().to_dict()

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate restaurant data by name + platform + city + crawl_id"
    )
    parser.add_argument(
        "--input", "-i",
        default=str(OUTPUT_CSV),
        help="Input CSV file"
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output CSV file (default: overwrites input)"
    )
    parser.add_argument(
        "--regenerate-files",
        action="store_true",
        help="Regenerate per-crawl/platform files"
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path

    # Deduplicate
    df = deduplicate_csv(input_path, output_path)

    # Regenerate per-crawl files if requested
    if args.regenerate_files:
        logger.info("\nRegenerating per-crawl/platform files...")
        regenerate_per_crawl_files(df)

    # Generate and save summary
    summary = generate_summary(df)
    summary_path = output_path.with_suffix('.summary.json')
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    # Print summary
    print("\n" + "="*60)
    print("DEDUPLICATION SUMMARY")
    print("="*60)
    print(f"Total unique restaurants: {summary['total_restaurants']:,}")

    print("\nBy platform:")
    for platform, count in sorted(summary['by_platform'].items()):
        print(f"  {platform}: {count:,}")

    print("\nBy crawl and platform:")
    print(f"  {'Crawl':<20} {'Glovo':>10} {'Just Eat':>10} {'Uber Eats':>10} {'Total':>10}")
    print(f"  {'-'*60}")
    for crawl_id in sorted(summary['by_crawl_platform'].keys()):
        platforms = summary['by_crawl_platform'][crawl_id]
        total = sum(platforms.values())
        print(f"  {crawl_id:<20} {platforms.get('Glovo', 0):>10,} {platforms.get('Just Eat', 0):>10,} {platforms.get('Uber Eats', 0):>10,} {total:>10,}")

    print(f"\nOutput: {output_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
