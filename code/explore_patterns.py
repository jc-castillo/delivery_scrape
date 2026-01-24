#!/usr/bin/env python3
"""
Explore URL patterns in Common Crawl to understand page structure.
"""
import boto3
import time
from config import (
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION,
    ATHENA_OUTPUT_LOCATION, ATHENA_DATABASE
)

athena = boto3.client(
    'athena',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)


def run_query(query: str, description: str) -> list:
    """Run an Athena query and return results."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"{'='*60}")

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

    if state == 'SUCCEEDED':
        results = athena.get_query_results(QueryExecutionId=execution_id)
        rows = results['ResultSet']['Rows']
        return rows
    else:
        reason = status['QueryExecution']['Status'].get('StateChangeReason', 'Unknown')
        print(f"Query failed: {reason}")
        return []


def print_results(rows, max_rows=20):
    """Print query results in a formatted table."""
    if not rows:
        print("No results")
        return

    headers = [col.get('VarCharValue', '') for col in rows[0]['Data']]
    print(f"{'  '.join(headers)}")
    print("-" * 80)

    for row in rows[1:max_rows+1]:
        values = [col.get('VarCharValue', '') for col in row['Data']]
        # Truncate long values
        values = [v[:70] if len(v) > 70 else v for v in values]
        print(f"  {values[0]:70s} {values[1] if len(values) > 1 else ''}")


# Queries to understand URL patterns
queries = {
    "Glovo URL path patterns": """
        SELECT
            regexp_extract(url_path, '^(/es/es/[^/]+/[^/]+)', 1) as pattern,
            COUNT(*) as cnt
        FROM ccindex.ccindex
        WHERE crawl = 'CC-MAIN-2023-23'
          AND subset = 'warc'
          AND url_host_registered_domain = 'glovoapp.com'
          AND url_protocol = 'https'
          AND fetch_status = 200
          AND url_path LIKE '/es/es/%'
        GROUP BY 1
        HAVING COUNT(*) > 5
        ORDER BY cnt DESC
        LIMIT 30
    """,

    "Uber Eats URL path patterns": """
        SELECT
            regexp_extract(url_path, '^(/[^/]+/[^/]+)', 1) as pattern,
            COUNT(*) as cnt
        FROM ccindex.ccindex
        WHERE crawl = 'CC-MAIN-2023-23'
          AND subset = 'warc'
          AND url_host_registered_domain = 'ubereats.com'
          AND url_protocol = 'https'
          AND fetch_status = 200
          AND (url_path LIKE '/es/%' OR url_path LIKE '/es-en/%' OR url_path LIKE '/es-ES/%')
        GROUP BY 1
        HAVING COUNT(*) > 5
        ORDER BY cnt DESC
        LIMIT 30
    """,

    "Just Eat URL path patterns": """
        SELECT
            CASE
                WHEN url_path = '/' THEN '/'
                WHEN url_path LIKE '/area/%' THEN '/area/...'
                WHEN url_path LIKE '/restaurants-%' THEN '/restaurants-...'
                WHEN url_path LIKE '/en/%' THEN '/en/...'
                WHEN url_path LIKE '/info/%' THEN '/info/...'
                ELSE regexp_extract(url_path, '^(/[^/?]+)', 1)
            END as pattern,
            COUNT(*) as cnt
        FROM ccindex.ccindex
        WHERE crawl = 'CC-MAIN-2023-23'
          AND subset = 'warc'
          AND url_host_registered_domain = 'just-eat.es'
          AND url_protocol = 'https'
          AND fetch_status = 200
        GROUP BY 1
        HAVING COUNT(*) > 3
        ORDER BY cnt DESC
        LIMIT 30
    """,

    "Sample Glovo store URLs": """
        SELECT url
        FROM ccindex.ccindex
        WHERE crawl = 'CC-MAIN-2023-23'
          AND subset = 'warc'
          AND url_host_registered_domain = 'glovoapp.com'
          AND url_protocol = 'https'
          AND fetch_status = 200
          AND url_path LIKE '/es/es/%'
          AND url_path NOT LIKE '%?%'
        LIMIT 20
    """,

    "Sample Just Eat area/city URLs": """
        SELECT url
        FROM ccindex.ccindex
        WHERE crawl = 'CC-MAIN-2023-23'
          AND subset = 'warc'
          AND url_host_registered_domain = 'just-eat.es'
          AND url_protocol = 'https'
          AND fetch_status = 200
          AND (url_path LIKE '/area/%' OR url_path LIKE '/restaurants-%')
        LIMIT 20
    """,
}

if __name__ == "__main__":
    for desc, query in queries.items():
        rows = run_query(query, desc)
        print_results(rows)
