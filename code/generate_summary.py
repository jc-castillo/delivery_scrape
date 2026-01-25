"""
Generate summary dataset at crawl x platform x city level.

Reads the per-crawl/per-platform parquet files and aggregates
restaurant counts by crawl, platform, and city.
"""
import pandas as pd
from pathlib import Path

from config import DATA_DIR

RESTAURANTS_DIR = DATA_DIR / "restaurants"
SUMMARY_OUTPUT = DATA_DIR / "summary"


def generate_summary():
    """
    Generate summary dataset with restaurant counts by crawl, platform, city.

    Outputs:
        - summary_by_crawl_platform_city.csv
        - summary_by_crawl_platform_city.parquet
    """
    SUMMARY_OUTPUT.mkdir(parents=True, exist_ok=True)

    # Find all parquet files
    parquet_files = list(RESTAURANTS_DIR.glob("*.parquet"))

    if not parquet_files:
        print("No parquet files found in", RESTAURANTS_DIR)
        return

    print(f"Found {len(parquet_files)} parquet files")

    # Read and aggregate each file
    all_summaries = []

    for pq_file in sorted(parquet_files):
        # Parse crawl_id and platform from filename
        # Format: CC-MAIN-2024-18_Just Eat.parquet
        name_parts = pq_file.stem.rsplit('_', 1)
        if len(name_parts) != 2:
            print(f"  Skipping {pq_file.name} - unexpected format")
            continue

        crawl_id, platform = name_parts

        # Read parquet
        df = pd.read_parquet(pq_file)

        # Group by city and count
        city_counts = df.groupby('city').size().reset_index(name='restaurant_count')
        city_counts['crawl_id'] = crawl_id
        city_counts['platform'] = platform

        all_summaries.append(city_counts)
        print(f"  {pq_file.name}: {len(city_counts)} cities, {len(df)} restaurants")

    # Combine all summaries
    summary_df = pd.concat(all_summaries, ignore_index=True)

    # Reorder columns
    summary_df = summary_df[['crawl_id', 'platform', 'city', 'restaurant_count']]

    # Sort by crawl_id, platform, city
    summary_df = summary_df.sort_values(['crawl_id', 'platform', 'city']).reset_index(drop=True)

    # Save as CSV
    csv_path = SUMMARY_OUTPUT / "summary_by_crawl_platform_city.csv"
    summary_df.to_csv(csv_path, index=False, encoding='utf-8')
    print(f"\nSaved CSV: {csv_path}")

    # Save as Parquet
    parquet_path = SUMMARY_OUTPUT / "summary_by_crawl_platform_city.parquet"
    summary_df.to_parquet(parquet_path, index=False, engine='pyarrow')
    print(f"Saved Parquet: {parquet_path}")

    # Print summary stats
    print(f"\nSummary statistics:")
    print(f"  Total rows: {len(summary_df)}")
    print(f"  Unique crawls: {summary_df['crawl_id'].nunique()}")
    print(f"  Unique platforms: {summary_df['platform'].nunique()}")
    print(f"  Unique cities: {summary_df['city'].nunique()}")
    print(f"  Total restaurants: {summary_df['restaurant_count'].sum():,}")

    # Show sample
    print(f"\nSample rows:")
    print(summary_df.head(10).to_string(index=False))

    return summary_df


if __name__ == "__main__":
    generate_summary()
