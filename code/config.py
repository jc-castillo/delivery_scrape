"""
Configuration settings for the Common Crawl scraper.
"""
import csv
import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
CODE_DIR = PROJECT_ROOT / "code"
DATA_DIR = PROJECT_ROOT / "data"
PAGES_DIR = PROJECT_ROOT / "pages"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PAGES_DIR.mkdir(exist_ok=True)


def load_aws_credentials():
    """
    Load AWS credentials from various sources in order of priority:
    1. Environment variables
    2. CSV file in Downloads (for initial setup)
    3. Default AWS credentials file (~/.aws/credentials)
    """
    # First, check environment variables
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

    if access_key and secret_key:
        return access_key, secret_key

    # Second, try to read from the downloaded CSV file
    csv_paths = [
        Path.home() / "Downloads" / "claude-v2_accessKeys.csv",
        Path.home() / ".aws" / "accessKeys.csv",
    ]

    for csv_path in csv_paths:
        if csv_path.exists():
            try:
                with open(csv_path, 'r', encoding='utf-8-sig') as f:
                    reader = csv.DictReader(f)
                    row = next(reader)
                    access_key = row.get('Access key ID', '')
                    secret_key = row.get('Secret access key', '')
                    if access_key and secret_key:
                        return access_key, secret_key
            except (StopIteration, KeyError, IOError):
                continue

    # Return empty strings if nothing found (boto3 will try ~/.aws/credentials)
    return "", ""


# AWS Configuration
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY = load_aws_credentials()
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Athena Configuration
ATHENA_DATABASE = "ccindex"
ATHENA_TABLE = "ccindex"
# Use a dedicated subfolder for this project to avoid mixing with existing data
ATHENA_OUTPUT_LOCATION = "s3://cc-food-delivery-queries/delivery-scrape-2025/athena-results"

# Common Crawl settings
CC_BUCKET = "commoncrawl"
CC_INDEX_BUCKET = "commoncrawl"

# Common Crawl indexes from 2022 to present (2022-2025)
# Format: CC-MAIN-YYYY-WW where WW is the crawl number
CC_INDEXES = [
    # 2022
    "CC-MAIN-2022-05", "CC-MAIN-2022-21", "CC-MAIN-2022-27",
    "CC-MAIN-2022-33", "CC-MAIN-2022-40", "CC-MAIN-2022-49",
    # 2023
    "CC-MAIN-2023-06", "CC-MAIN-2023-14", "CC-MAIN-2023-23",
    "CC-MAIN-2023-40", "CC-MAIN-2023-50",
    # 2024
    "CC-MAIN-2024-10", "CC-MAIN-2024-18", "CC-MAIN-2024-22",
    "CC-MAIN-2024-26", "CC-MAIN-2024-30", "CC-MAIN-2024-33",
    "CC-MAIN-2024-38", "CC-MAIN-2024-42", "CC-MAIN-2024-46",
    "CC-MAIN-2024-51",
    # 2025
    "CC-MAIN-2025-03", "CC-MAIN-2025-08", "CC-MAIN-2025-13",
]

# Target platforms and their Athena query configurations
PLATFORMS = {
    "glovo": {
        "name": "Glovo",
        "domain": "glovoapp.com",
        "host": "glovoapp.com",
        "url_path_pattern": "/es/es/%",  # Spanish pages
        # Restaurant listing patterns - these list restaurants in a city
        "listing_patterns": [
            r"glovoapp\.com/es/es/[^/]+/restaurants.*",  # City restaurant listings
            r"glovoapp\.com/es/es/[^/]+/category/.*",    # Category pages
        ],
        # Individual restaurant patterns
        "restaurant_patterns": [
            r"glovoapp\.com/es/es/[^/]+/store/.*",       # Individual stores
        ],
    },
    "ubereats": {
        "name": "Uber Eats",
        "domain": "ubereats.com",
        "host": "www.ubereats.com",
        "url_path_pattern": "/es%",  # Spanish pages (includes /es/ and /es-ES/)
        "listing_patterns": [
            r"ubereats\.com/es/city/[^/]+$",             # City main page
            r"ubereats\.com/es/city/[^/]+/.*",           # City category pages
            r"ubereats\.com/es-ES/city/[^/]+.*",         # Alternative ES format
        ],
        "restaurant_patterns": [
            r"ubereats\.com/es/store/.*",                # Store pages
            r"ubereats\.com/es-ES/store/.*",             # Alternative format
        ],
    },
    "justeat": {
        "name": "Just Eat",
        "domain": "just-eat.es",
        "host": "www.just-eat.es",
        "url_path_pattern": "/%",  # All pages (domain is already Spain-specific)
        "listing_patterns": [
            r"just-eat\.es/[^/]+$",                      # City pages (e.g., /madrid)
            r"just-eat\.es/area/.*",                     # Area pages
            r"justeat\.es/[^/]+$",
        ],
        "restaurant_patterns": [
            r"just-eat\.es/restaurants-.*",              # Restaurant pages
            r"justeat\.es/restaurants-.*",
        ],
    },
}

# Spanish cities to focus on
SPANISH_CITIES = [
    "madrid", "barcelona", "valencia", "sevilla", "zaragoza",
    "malaga", "murcia", "palma", "las-palmas", "bilbao",
    "alicante", "cordoba", "valladolid", "vigo", "gijon",
    "granada", "elche", "oviedo", "santa-cruz-de-tenerife",
    "pamplona", "santander", "almeria", "san-sebastian",
    "burgos", "salamanca", "leon", "tarragona", "cadiz",
]

# Rate limiting
REQUEST_DELAY = 0.1  # seconds between requests
MAX_RETRIES = 3

# Output settings
OUTPUT_CSV = DATA_DIR / "restaurants_spain.csv"
INDEX_CACHE_DIR = DATA_DIR / "index_cache"
INDEX_CACHE_DIR.mkdir(exist_ok=True)
