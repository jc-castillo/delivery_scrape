"""
Common Crawl Index querying module.

This module queries the Common Crawl index to find URLs matching our target platforms.
Uses AWS S3 for efficient access to the index files.
"""
import gzip
import json
import logging
from pathlib import Path
from typing import Iterator, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore import UNSIGNED

from config import (
    CC_BUCKET, CC_INDEXES, PLATFORMS, DATA_DIR, INDEX_CACHE_DIR,
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CommonCrawlIndex:
    """Query Common Crawl index via AWS S3."""

    def __init__(self, use_aws_credentials: bool = True):
        """
        Initialize the Common Crawl index client.

        Args:
            use_aws_credentials: If True, use AWS credentials for faster access.
                                If False, use unsigned requests (slower, rate limited).
        """
        if use_aws_credentials and AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
            self.s3 = boto3.client(
                's3',
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
            )
            logger.info("Using AWS credentials for S3 access")
        else:
            # Use unsigned requests for public access
            self.s3 = boto3.client(
                's3',
                config=Config(signature_version=UNSIGNED),
                region_name='us-east-1',
            )
            logger.info("Using unsigned requests for S3 access (may be rate limited)")

    def get_index_cluster_paths(self, crawl_id: str) -> list[str]:
        """
        Get all cluster.idx file paths for a given crawl.

        The Common Crawl index is sharded across multiple files.
        """
        prefix = f"cc-index/collections/{crawl_id}/indexes/"

        try:
            response = self.s3.list_objects_v2(
                Bucket=CC_BUCKET,
                Prefix=prefix,
                Delimiter='/'
            )

            # Get the cdx-* subdirectories
            paths = []
            if 'CommonPrefixes' in response:
                for prefix_obj in response['CommonPrefixes']:
                    cdx_prefix = prefix_obj['Prefix']
                    # List files in this cdx directory
                    files_response = self.s3.list_objects_v2(
                        Bucket=CC_BUCKET,
                        Prefix=cdx_prefix
                    )
                    for obj in files_response.get('Contents', []):
                        if obj['Key'].endswith('.gz'):
                            paths.append(obj['Key'])

            return paths
        except Exception as e:
            logger.error(f"Error getting index paths for {crawl_id}: {e}")
            return []

    def query_cdx_api(self, domain: str, crawl_id: str,
                      match_type: str = "domain") -> Iterator[dict]:
        """
        Query the CDX API for URLs matching a domain.

        This is the simpler approach using the CDX API.

        Args:
            domain: Domain to search for (e.g., 'glovoapp.com')
            crawl_id: Common Crawl index ID (e.g., 'CC-MAIN-2024-51')
            match_type: 'domain', 'host', 'prefix', or 'exact'

        Yields:
            Dictionary with URL metadata
        """
        import requests

        # CDX API endpoint
        api_url = f"https://index.commoncrawl.org/{crawl_id}-index"

        params = {
            "url": domain,
            "matchType": match_type,
            "output": "json",
            "filter": "status:200",  # Only successful responses
        }

        try:
            response = requests.get(api_url, params=params, stream=True)
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        yield json.loads(line.decode('utf-8'))
                    except json.JSONDecodeError:
                        continue

        except requests.RequestException as e:
            logger.error(f"CDX API error for {domain} in {crawl_id}: {e}")

    def query_index_via_s3(self, domain: str, crawl_id: str) -> Iterator[dict]:
        """
        Query the Common Crawl index directly via S3.

        This is more efficient for bulk queries as it avoids API rate limits.

        Args:
            domain: Domain to search for
            crawl_id: Common Crawl index ID

        Yields:
            Dictionary with URL metadata
        """
        # Reverse the domain for index lookup (Common Crawl uses reversed domain sort)
        reversed_domain = ','.join(reversed(domain.split('.')))

        # Get the cluster.idx to find which shard contains our domain
        cluster_idx_key = f"cc-index/collections/{crawl_id}/indexes/cluster.idx"

        try:
            response = self.s3.get_object(Bucket=CC_BUCKET, Key=cluster_idx_key)
            cluster_idx = response['Body'].read().decode('utf-8')

            # Find the shard that contains our domain
            target_shard = None
            prev_shard = None

            for line in cluster_idx.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 2:
                    shard_key = parts[0]
                    shard_file = parts[1]

                    if shard_key > reversed_domain:
                        target_shard = prev_shard or shard_file
                        break
                    prev_shard = shard_file

            if not target_shard:
                target_shard = prev_shard

            if target_shard:
                # Query the specific shard
                yield from self._query_shard(crawl_id, target_shard, domain)

        except Exception as e:
            logger.error(f"S3 index query error for {domain} in {crawl_id}: {e}")

    def _query_shard(self, crawl_id: str, shard_file: str,
                     domain: str) -> Iterator[dict]:
        """Query a specific index shard for matching URLs."""
        shard_key = f"cc-index/collections/{crawl_id}/indexes/{shard_file}"

        try:
            response = self.s3.get_object(Bucket=CC_BUCKET, Key=shard_key)

            # Decompress and search
            with gzip.GzipFile(fileobj=response['Body']) as gz:
                for line in gz:
                    try:
                        # CDX format: URL timestamp JSON
                        line_str = line.decode('utf-8').strip()
                        parts = line_str.split(' ', 2)

                        if len(parts) >= 3:
                            url_key, timestamp, json_str = parts

                            # Check if this URL matches our domain
                            if domain in url_key or domain.replace('.', ',') in url_key:
                                record = json.loads(json_str)
                                record['urlkey'] = url_key
                                record['timestamp'] = timestamp
                                yield record

                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue

        except Exception as e:
            logger.error(f"Error querying shard {shard_file}: {e}")

    def find_platform_urls(self, platform_key: str, crawl_id: str,
                          use_api: bool = True) -> list[dict]:
        """
        Find all URLs for a specific platform in a crawl.

        Args:
            platform_key: Key from PLATFORMS dict (e.g., 'glovo')
            crawl_id: Common Crawl index ID
            use_api: If True, use CDX API. If False, use direct S3 access.

        Returns:
            List of URL records
        """
        platform = PLATFORMS[platform_key]
        results = []

        for domain in platform['domains']:
            logger.info(f"Querying {domain} in {crawl_id}...")

            if use_api:
                records = list(self.query_cdx_api(domain, crawl_id))
            else:
                records = list(self.query_index_via_s3(domain, crawl_id))

            results.extend(records)
            logger.info(f"Found {len(records)} URLs for {domain}")

        return results

    def find_all_platform_urls(self, crawl_ids: Optional[list[str]] = None,
                               use_api: bool = True,
                               save_intermediate: bool = True) -> dict:
        """
        Find URLs for all platforms across multiple crawls.

        Args:
            crawl_ids: List of crawl IDs to query. Defaults to CC_INDEXES.
            use_api: Whether to use the CDX API or direct S3 access.
            save_intermediate: Whether to save results after each crawl.

        Returns:
            Dictionary mapping crawl_id -> platform -> list of URL records
        """
        if crawl_ids is None:
            crawl_ids = CC_INDEXES

        all_results = {}

        for crawl_id in crawl_ids:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing crawl: {crawl_id}")
            logger.info(f"{'='*50}")

            crawl_results = {}

            for platform_key in PLATFORMS:
                urls = self.find_platform_urls(platform_key, crawl_id, use_api)
                crawl_results[platform_key] = urls

            all_results[crawl_id] = crawl_results

            if save_intermediate:
                self._save_index_cache(crawl_id, crawl_results)

        return all_results

    def _save_index_cache(self, crawl_id: str, results: dict):
        """Save index query results to cache."""
        cache_file = INDEX_CACHE_DIR / f"{crawl_id}_index.json"

        with open(cache_file, 'w') as f:
            json.dump(results, f, indent=2)

        logger.info(f"Saved index cache to {cache_file}")

    def load_index_cache(self, crawl_id: str) -> Optional[dict]:
        """Load cached index results if available."""
        cache_file = INDEX_CACHE_DIR / f"{crawl_id}_index.json"

        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)
        return None


def main():
    """Main function to query Common Crawl index."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Query Common Crawl index for food delivery platforms"
    )
    parser.add_argument(
        "--crawl", "-c",
        help="Specific crawl ID to query (default: query all)",
        default=None
    )
    parser.add_argument(
        "--platform", "-p",
        choices=list(PLATFORMS.keys()),
        help="Specific platform to query (default: all)",
        default=None
    )
    parser.add_argument(
        "--use-s3",
        action="store_true",
        help="Use direct S3 access instead of CDX API"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file for results",
        default=str(DATA_DIR / "index_results.json")
    )

    args = parser.parse_args()

    # Initialize client
    cc_index = CommonCrawlIndex()

    # Determine which crawls to query
    crawl_ids = [args.crawl] if args.crawl else CC_INDEXES

    # Query the index
    if args.platform:
        # Query single platform
        results = {}
        for crawl_id in crawl_ids:
            urls = cc_index.find_platform_urls(
                args.platform, crawl_id, use_api=not args.use_s3
            )
            results[crawl_id] = {args.platform: urls}
    else:
        # Query all platforms
        results = cc_index.find_all_platform_urls(
            crawl_ids, use_api=not args.use_s3
        )

    # Save results
    with open(args.output, 'w') as f:
        json.dump(results, f, indent=2)

    # Print summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)

    total_urls = 0
    for crawl_id, platforms in results.items():
        crawl_total = sum(len(urls) for urls in platforms.values())
        total_urls += crawl_total
        print(f"{crawl_id}: {crawl_total} URLs")
        for platform, urls in platforms.items():
            print(f"  {platform}: {len(urls)}")

    print(f"\nTotal URLs found: {total_urls}")
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
