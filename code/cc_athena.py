"""
Common Crawl Index querying via AWS Athena.

This is much faster than the CDX API for bulk queries.
Athena queries the Common Crawl index directly from S3.
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import boto3

from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    ATHENA_DATABASE, ATHENA_OUTPUT_LOCATION,
    CC_INDEXES, PLATFORMS, INDEX_CACHE_DIR
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AthenaIndexQuery:
    """Query Common Crawl index using AWS Athena."""

    def __init__(self):
        """Initialize Athena client."""
        self.athena = boto3.client(
            'athena',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
        self.s3 = boto3.client(
            's3',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )

        # Log the output location being used
        logger.info(f"Athena results will be stored in: {ATHENA_OUTPUT_LOCATION}")

    def build_query(self, platform_key: str, crawl_id: str) -> str:
        """
        Build Athena SQL query for a platform and crawl.

        Args:
            platform_key: Key from PLATFORMS dict
            crawl_id: Common Crawl ID (e.g., 'CC-MAIN-2024-51')

        Returns:
            SQL query string
        """
        # Validate crawl_id to prevent SQL injection
        if not re.match(r'^[A-Za-z0-9\-]+$', crawl_id):
            raise ValueError(f"Invalid crawl_id format: {crawl_id}")

        platform = PLATFORMS[platform_key]

        query = f"""
        SELECT
            url,
            fetch_time,
            fetch_status,
            content_mime_detected,
            warc_filename,
            warc_record_offset,
            warc_record_length
        FROM {ATHENA_DATABASE}.ccindex
        WHERE crawl = '{crawl_id}'
          AND subset = 'warc'
          AND url_host_registered_domain = '{platform["domain"]}'
          AND url_protocol = 'https'
          AND fetch_status = 200
          AND content_mime_detected = 'text/html'
          AND url_path LIKE '{platform["url_path_pattern"]}'
        """

        # Add host filter if specified
        if platform.get("host"):
            query += f"  AND url_host_name = '{platform['host']}'\n"

        query += "ORDER BY url"

        return query

    def execute_query(self, query: str, description: str = "") -> str:
        """
        Execute an Athena query and return the query execution ID.

        Args:
            query: SQL query to execute
            description: Optional description for logging

        Returns:
            Query execution ID
        """
        logger.info(f"Executing Athena query: {description}")
        logger.debug(f"Query: {query}")

        response = self.athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={'Database': ATHENA_DATABASE},
            ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_LOCATION},
        )

        return response['QueryExecutionId']

    def wait_for_query(self, execution_id: str, timeout: int = 300) -> dict:
        """
        Wait for query to complete and return status.

        Args:
            execution_id: Query execution ID
            timeout: Maximum wait time in seconds

        Returns:
            Query execution status dict
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = self.athena.get_query_execution(
                QueryExecutionId=execution_id
            )
            status = response['QueryExecution']['Status']
            state = status['State']

            if state == 'SUCCEEDED':
                logger.info(f"Query {execution_id} succeeded")
                return response['QueryExecution']
            elif state in ('FAILED', 'CANCELLED'):
                reason = status.get('StateChangeReason', 'Unknown')
                raise Exception(f"Query {state}: {reason}")

            logger.debug(f"Query state: {state}, waiting...")
            time.sleep(2)

        raise TimeoutError(f"Query {execution_id} timed out after {timeout}s")

    def get_query_results(self, execution_id: str) -> list[dict]:
        """
        Get results from a completed query.

        Args:
            execution_id: Query execution ID

        Returns:
            List of result rows as dictionaries
        """
        results = []
        paginator = self.athena.get_paginator('get_query_results')

        for page in paginator.paginate(QueryExecutionId=execution_id):
            rows = page['ResultSet']['Rows']

            # First row is headers
            if not results:
                headers = [col['VarCharValue'] for col in rows[0]['Data']]
                rows = rows[1:]

            for row in rows:
                values = [col.get('VarCharValue', '') for col in row['Data']]
                results.append(dict(zip(headers, values)))

        return results

    def query_platform(self, platform_key: str, crawl_id: str,
                      use_cache: bool = True) -> list[dict]:
        """
        Query URLs for a platform in a specific crawl.

        Args:
            platform_key: Key from PLATFORMS dict
            crawl_id: Common Crawl ID
            use_cache: Whether to use cached results

        Returns:
            List of URL records
        """
        # Check cache first
        cache_file = INDEX_CACHE_DIR / f"{crawl_id}_{platform_key}_athena.json"
        if use_cache and cache_file.exists():
            logger.info(f"Loading cached results for {platform_key} in {crawl_id}")
            with open(cache_file) as f:
                return json.load(f)

        # Build and execute query
        query = self.build_query(platform_key, crawl_id)
        execution_id = self.execute_query(
            query,
            description=f"{platform_key} in {crawl_id}"
        )

        # Wait for completion
        self.wait_for_query(execution_id)

        # Get results
        results = self.get_query_results(execution_id)
        logger.info(f"Found {len(results)} URLs for {platform_key} in {crawl_id}")

        # Cache results
        with open(cache_file, 'w') as f:
            json.dump(results, f, indent=2)

        return results

    def query_all_platforms(self, crawl_id: str,
                           use_cache: bool = True) -> dict[str, list[dict]]:
        """
        Query all platforms for a specific crawl.

        Args:
            crawl_id: Common Crawl ID
            use_cache: Whether to use cached results

        Returns:
            Dict mapping platform_key -> list of URL records
        """
        results = {}

        for platform_key in PLATFORMS:
            try:
                platform_results = self.query_platform(
                    platform_key, crawl_id, use_cache
                )
                results[platform_key] = platform_results
            except Exception as e:
                logger.error(f"Error querying {platform_key}: {e}")
                results[platform_key] = []

        return results

    def query_all_crawls(self, crawl_ids: Optional[list[str]] = None,
                        use_cache: bool = True) -> dict[str, dict[str, list[dict]]]:
        """
        Query all platforms across multiple crawls.

        Args:
            crawl_ids: List of crawl IDs (defaults to CC_INDEXES)
            use_cache: Whether to use cached results

        Returns:
            Dict mapping crawl_id -> platform_key -> list of URL records
        """
        if crawl_ids is None:
            crawl_ids = CC_INDEXES

        all_results = {}

        for crawl_id in crawl_ids:
            logger.info(f"\n{'='*50}")
            logger.info(f"Processing {crawl_id}")
            logger.info(f"{'='*50}")

            try:
                crawl_results = self.query_all_platforms(crawl_id, use_cache)
                all_results[crawl_id] = crawl_results

                # Summary
                total = sum(len(urls) for urls in crawl_results.values())
                logger.info(f"Total URLs in {crawl_id}: {total}")

            except Exception as e:
                logger.error(f"Error processing {crawl_id}: {e}")
                all_results[crawl_id] = {}

        return all_results


def main():
    """Test Athena queries."""
    import argparse

    parser = argparse.ArgumentParser(description="Query Common Crawl via Athena")
    parser.add_argument("--crawl", "-c", help="Specific crawl ID")
    parser.add_argument("--platform", "-p", choices=list(PLATFORMS.keys()))
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", "-o", default="data/athena_results.json")

    args = parser.parse_args()

    querier = AthenaIndexQuery()

    if args.crawl and args.platform:
        results = querier.query_platform(
            args.platform, args.crawl, use_cache=not args.no_cache
        )
        print(f"Found {len(results)} URLs")
    elif args.crawl:
        results = querier.query_all_platforms(
            args.crawl, use_cache=not args.no_cache
        )
        for platform, urls in results.items():
            print(f"{platform}: {len(urls)} URLs")
    else:
        # Query single crawl as test
        test_crawl = "CC-MAIN-2024-51"
        print(f"Testing with {test_crawl}")
        results = querier.query_all_platforms(
            test_crawl, use_cache=not args.no_cache
        )
        for platform, urls in results.items():
            print(f"{platform}: {len(urls)} URLs")


if __name__ == "__main__":
    main()
