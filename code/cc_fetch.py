"""
Common Crawl WARC fetching module.

This module downloads HTML content from Common Crawl WARC files.
"""
import gzip
import hashlib
import json
import logging
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import boto3
from botocore.config import Config
from botocore import UNSIGNED

from config import (
    CC_BUCKET, PLATFORMS, PAGES_DIR, DATA_DIR,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    REQUEST_DELAY, MAX_RETRIES
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class WARCRecord:
    """Represents a WARC record with metadata and content."""
    url: str
    timestamp: str
    status: int
    mime_type: str
    content: bytes
    crawl_id: str
    platform: str

    @property
    def html(self) -> str:
        """Decode content as HTML string."""
        try:
            return self.content.decode('utf-8')
        except UnicodeDecodeError:
            return self.content.decode('latin-1')


class CommonCrawlFetcher:
    """Fetch HTML content from Common Crawl WARC files."""

    def __init__(self, use_aws_credentials: bool = True):
        """Initialize the fetcher with S3 client."""
        if use_aws_credentials and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            self.s3 = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
            )
            logger.info("Using AWS credentials for S3 access")
        else:
            self.s3 = boto3.client(
                's3',
                config=Config(signature_version=UNSIGNED),
                region_name='us-east-1',
            )
            logger.info("Using unsigned requests for S3 access")

    def fetch_warc_record(self, record: dict) -> Optional[WARCRecord]:
        """
        Fetch a single WARC record from Common Crawl.

        Args:
            record: CDX record with filename, offset, and length

        Returns:
            WARCRecord with content, or None if fetch fails
        """
        filename = record.get('filename')
        offset = int(record.get('offset', 0))
        length = int(record.get('length', 0))

        if not filename or not length:
            logger.warning(f"Invalid record: missing filename or length")
            return None

        # Calculate byte range
        end_byte = offset + length - 1

        for attempt in range(MAX_RETRIES):
            try:
                response = self.s3.get_object(
                    Bucket=CC_BUCKET,
                    Key=filename,
                    Range=f"bytes={offset}-{end_byte}"
                )

                # Decompress the WARC record
                compressed_data = response['Body'].read()
                warc_data = gzip.decompress(compressed_data)

                # Parse WARC record
                content = self._parse_warc_response(warc_data)

                if content:
                    return WARCRecord(
                        url=record.get('url', ''),
                        timestamp=record.get('timestamp', ''),
                        status=int(record.get('status', 0)),
                        mime_type=record.get('mime', 'text/html'),
                        content=content,
                        crawl_id=record.get('crawl_id', ''),
                        platform=record.get('platform', ''),
                    )

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {filename}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(REQUEST_DELAY * (attempt + 1))

        return None

    def _parse_warc_response(self, warc_data: bytes) -> Optional[bytes]:
        """
        Parse WARC response record to extract HTTP body.

        WARC format:
        1. WARC headers
        2. Blank line
        3. HTTP response headers
        4. Blank line
        5. HTTP body (what we want)
        """
        try:
            # Find end of WARC headers
            warc_header_end = warc_data.find(b'\r\n\r\n')
            if warc_header_end == -1:
                return None

            http_response = warc_data[warc_header_end + 4:]

            # Find end of HTTP headers
            http_header_end = http_response.find(b'\r\n\r\n')
            if http_header_end == -1:
                http_header_end = http_response.find(b'\n\n')
                if http_header_end == -1:
                    return None
                body = http_response[http_header_end + 2:]
            else:
                body = http_response[http_header_end + 4:]

            return body

        except Exception as e:
            logger.error(f"Error parsing WARC: {e}")
            return None

    def fetch_multiple(self, records: list[dict],
                      max_workers: int = 10) -> list[WARCRecord]:
        """
        Fetch multiple WARC records in parallel.

        Args:
            records: List of CDX records
            max_workers: Number of parallel workers

        Returns:
            List of successfully fetched WARCRecords
        """
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_record = {
                executor.submit(self.fetch_warc_record, record): record
                for record in records
            }

            for i, future in enumerate(as_completed(future_to_record)):
                record = future_to_record[future]
                try:
                    warc_record = future.result()
                    if warc_record:
                        results.append(warc_record)
                        logger.info(f"Fetched {i+1}/{len(records)}: {record.get('url', '')[:80]}")
                except Exception as e:
                    logger.error(f"Error fetching {record.get('url', '')}: {e}")

                # Small delay to avoid overwhelming S3
                time.sleep(REQUEST_DELAY)

        return results

    def save_html(self, warc_record: WARCRecord,
                  output_dir: Optional[Path] = None) -> Path:
        """
        Save HTML content to disk.

        Args:
            warc_record: WARC record with content
            output_dir: Output directory (default: PAGES_DIR)

        Returns:
            Path to saved file
        """
        if output_dir is None:
            output_dir = PAGES_DIR

        # Create subdirectory structure: platform/crawl_id/
        save_dir = output_dir / warc_record.platform / warc_record.crawl_id
        save_dir.mkdir(parents=True, exist_ok=True)

        # Create filename from URL hash + timestamp
        url_hash = hashlib.md5(warc_record.url.encode()).hexdigest()[:12]
        filename = f"{warc_record.timestamp}_{url_hash}.html"

        filepath = save_dir / filename

        # Save HTML content
        with open(filepath, 'wb') as f:
            f.write(warc_record.content)

        # Save metadata
        meta_filepath = filepath.with_suffix('.json')
        with open(meta_filepath, 'w') as f:
            json.dump({
                'url': warc_record.url,
                'timestamp': warc_record.timestamp,
                'status': warc_record.status,
                'mime_type': warc_record.mime_type,
                'crawl_id': warc_record.crawl_id,
                'platform': warc_record.platform,
            }, f, indent=2)

        return filepath


def is_listing_page(url: str, platform: str) -> bool:
    """
    Check if a URL is a restaurant listing page (not individual restaurant).

    Args:
        url: URL to check
        platform: Platform key

    Returns:
        True if this is a listing page
    """
    if platform not in PLATFORMS:
        return False

    platform_config = PLATFORMS[platform]

    for pattern in platform_config.get('listing_patterns', []):
        if re.search(pattern, url):
            return True

    return False


def filter_listing_urls(records: list[dict], platform: str) -> list[dict]:
    """
    Filter records to only include restaurant listing pages.

    Args:
        records: List of CDX records
        platform: Platform key

    Returns:
        Filtered list of records
    """
    filtered = []

    for record in records:
        url = record.get('url', '')
        if is_listing_page(url, platform):
            record['platform'] = platform
            filtered.append(record)

    return filtered


def main():
    """Main function to fetch pages from Common Crawl."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch HTML pages from Common Crawl WARC files"
    )
    parser.add_argument(
        "--index-file", "-i",
        required=True,
        help="JSON file with index query results"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=10,
        help="Maximum pages to fetch per platform per crawl (for testing)"
    )
    parser.add_argument(
        "--listings-only",
        action="store_true",
        help="Only fetch restaurant listing pages"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=str(PAGES_DIR),
        help="Output directory for HTML files"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=10,
        help="Number of parallel workers"
    )

    args = parser.parse_args()

    # Load index results
    with open(args.index_file, 'r') as f:
        index_results = json.load(f)

    # Initialize fetcher
    fetcher = CommonCrawlFetcher()
    output_dir = Path(args.output_dir)

    total_fetched = 0

    for crawl_id, platforms in index_results.items():
        logger.info(f"\n{'='*50}")
        logger.info(f"Fetching from: {crawl_id}")
        logger.info(f"{'='*50}")

        for platform, records in platforms.items():
            if args.listings_only:
                records = filter_listing_urls(records, platform)

            # Add metadata to records
            for record in records:
                record['crawl_id'] = crawl_id
                record['platform'] = platform

            # Apply limit
            if args.limit:
                records = records[:args.limit]

            if not records:
                logger.info(f"No records for {platform}")
                continue

            logger.info(f"Fetching {len(records)} pages for {platform}...")

            # Fetch pages
            warc_records = fetcher.fetch_multiple(records, max_workers=args.workers)

            # Save pages
            for warc_record in warc_records:
                filepath = fetcher.save_html(warc_record, output_dir)
                logger.info(f"Saved: {filepath}")

            total_fetched += len(warc_records)

    print(f"\nTotal pages fetched: {total_fetched}")
    print(f"Saved to: {output_dir}")


if __name__ == "__main__":
    main()
