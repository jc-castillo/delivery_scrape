#!/usr/bin/env python3
"""
Download sample HTML pages from Common Crawl for each platform.
This helps us understand the page structure and update extractors.
"""
import boto3
import gzip
import json
import time
from pathlib import Path
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    ATHENA_OUTPUT_LOCATION, ATHENA_DATABASE, CC_BUCKET,
    PAGES_DIR
)

athena = boto3.client(
    'athena',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)


def run_query(query: str) -> list[dict]:
    """Run an Athena query and return results as list of dicts."""
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': ATHENA_DATABASE},
        ResultConfiguration={'OutputLocation': ATHENA_OUTPUT_LOCATION},
    )
    execution_id = response['QueryExecutionId']

    # Wait for completion
    while True:
        status = athena.get_query_execution(QueryExecutionId=execution_id)
        state = status['QueryExecution']['Status']['State']
        if state in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
            break
        time.sleep(1)

    if state != 'SUCCEEDED':
        reason = status['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
        raise Exception(f"Query failed: {reason}")

    # Get results
    results = []
    paginator = athena.get_paginator('get_query_results')
    headers = None

    for page in paginator.paginate(QueryExecutionId=execution_id):
        rows = page['ResultSet']['Rows']
        if headers is None:
            headers = [col.get('VarCharValue', '') for col in rows[0]['Data']]
            rows = rows[1:]

        for row in rows:
            values = [col.get('VarCharValue', '') for col in row['Data']]
            results.append(dict(zip(headers, values)))

    return results


def fetch_warc_record(record: dict) -> bytes:
    """Fetch and decompress a WARC record from S3."""
    filename = record['warc_filename']
    offset = int(record['warc_record_offset'])
    length = int(record['warc_record_length'])

    response = s3.get_object(
        Bucket=CC_BUCKET,
        Key=filename,
        Range=f"bytes={offset}-{offset + length - 1}"
    )

    compressed_data = response['Body'].read()
    warc_data = gzip.decompress(compressed_data)

    return warc_data


def extract_html_from_warc(warc_data: bytes) -> bytes:
    """Extract the HTML body from a WARC record."""
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


def save_sample(platform: str, crawl_id: str, url: str, html: bytes, record: dict):
    """Save a sample HTML file with metadata."""
    # Create directory structure
    sample_dir = PAGES_DIR / "samples" / platform / crawl_id
    sample_dir.mkdir(parents=True, exist_ok=True)

    # Create filename from URL
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    filename = f"{url_hash}.html"

    # Save HTML
    html_path = sample_dir / filename
    with open(html_path, 'wb') as f:
        f.write(html)

    # Save metadata
    meta_path = sample_dir / f"{url_hash}.json"
    with open(meta_path, 'w') as f:
        json.dump({
            'url': url,
            'crawl_id': crawl_id,
            'platform': platform,
            'warc_filename': record['warc_filename'],
            'fetch_time': record.get('fetch_time', ''),
        }, f, indent=2)

    print(f"  Saved: {html_path}")
    return html_path


# Define queries for listing pages (the pages that list multiple restaurants)
SAMPLE_QUERIES = {
    "glovo_listings": {
        "platform": "glovo",
        "description": "Glovo restaurant listing pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'glovoapp.com'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND url_path LIKE '/es/es/%/restaurantes%'
              AND url_path NOT LIKE '%?%'
            LIMIT 5
        """
    },
    "glovo_stores": {
        "platform": "glovo",
        "description": "Glovo individual store pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'glovoapp.com'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND url_path LIKE '/es/es/%'
              AND url_path NOT LIKE '%/restaurantes%'
              AND url_path NOT LIKE '%?%'
              AND url_path NOT LIKE '/es/es/'
              AND LENGTH(url_path) > 15
            LIMIT 5
        """
    },
    "ubereats_city": {
        "platform": "ubereats",
        "description": "Uber Eats city pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'ubereats.com'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND (url_path LIKE '/es/city/%' OR url_path LIKE '/es-en/city/%')
            LIMIT 5
        """
    },
    "ubereats_stores": {
        "platform": "ubereats",
        "description": "Uber Eats store pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'ubereats.com'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND (url_path LIKE '/es/store/%' OR url_path LIKE '/es-en/store/%')
            LIMIT 5
        """
    },
    "justeat_area": {
        "platform": "justeat",
        "description": "Just Eat area listing pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'just-eat.es'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND url_path LIKE '/area/%'
              AND url_path NOT LIKE '%/%/%'
            LIMIT 5
        """
    },
    "justeat_restaurants": {
        "platform": "justeat",
        "description": "Just Eat individual restaurant pages",
        "query": """
            SELECT url, warc_filename, warc_record_offset, warc_record_length, fetch_time
            FROM ccindex.ccindex
            WHERE crawl = 'CC-MAIN-2023-23'
              AND subset = 'warc'
              AND url_host_registered_domain = 'just-eat.es'
              AND url_protocol = 'https'
              AND fetch_status = 200
              AND content_mime_detected = 'text/html'
              AND url_path LIKE '/restaurants-%'
              AND url_path NOT LIKE '%?%'
            LIMIT 5
        """
    },
}


def main():
    crawl_id = "CC-MAIN-2023-23"

    for query_name, config in SAMPLE_QUERIES.items():
        print(f"\n{'='*60}")
        print(f"Downloading: {config['description']}")
        print(f"{'='*60}")

        try:
            records = run_query(config['query'])
            print(f"Found {len(records)} records")

            for record in records:
                url = record['url']
                print(f"\nFetching: {url}")

                try:
                    warc_data = fetch_warc_record(record)
                    html = extract_html_from_warc(warc_data)

                    if html:
                        save_sample(config['platform'], crawl_id, url, html, record)
                    else:
                        print(f"  Failed to extract HTML")
                except Exception as e:
                    print(f"  Error: {e}")

        except Exception as e:
            print(f"Query error: {e}")

    print("\n" + "="*60)
    print("Download complete! Check the pages/samples/ directory.")
    print("="*60)


if __name__ == "__main__":
    main()
