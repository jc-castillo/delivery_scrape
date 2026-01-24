# Food Delivery Restaurant Scraper (Spain)

Extract historical restaurant data from Glovo, Uber Eats, and Just Eat in Spain using Common Crawl archives (2022-present).

## Overview

This project extracts restaurant listings from Common Crawl snapshots of food delivery platforms, creating a dataset of restaurants available at different points in time.

**Output**: A CSV with columns:
- `date` - Snapshot date (YYYY-MM-DD)
- `city` - Spanish city
- `name` - Restaurant name
- `platform` - Glovo, Uber Eats, or Just Eat
- `address` - Street address (when available)
- `neighborhood` - Neighborhood/area
- `food_type` - Primary cuisine type
- `categories` - All cuisine categories
- `rating` - Restaurant rating
- `num_ratings` - Number of ratings
- `price_range` - Price category (€, €€, €€€)
- `delivery_fee` - Delivery cost
- `delivery_time` - Estimated delivery time
- And more...

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up AWS (Recommended)

See [AWS_SETUP.md](AWS_SETUP.md) for detailed instructions. In brief:

```bash
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"
```

### 3. Run the Pipeline

```bash
cd code

# Full pipeline (all crawls, all platforms)
python run_pipeline.py --all

# Or test with a single crawl and limited pages
python run_pipeline.py --all --crawl CC-MAIN-2024-51 --limit 100
```

## Project Structure

```
delivery_scrape/
├── code/
│   ├── config.py           # Configuration and settings
│   ├── cc_index.py         # Common Crawl index querying
│   ├── cc_fetch.py         # WARC file fetching
│   ├── extract_data.py     # Data extraction to CSV
│   ├── analyze_pages.py    # Page structure analysis
│   ├── run_pipeline.py     # Main orchestration script
│   └── extractors/
│       ├── __init__.py
│       ├── base.py         # Base extractor class
│       ├── glovo.py        # Glovo-specific extraction
│       ├── ubereats.py     # Uber Eats extraction
│       └── justeat.py      # Just Eat extraction
├── data/                   # Output data and caches
│   └── index_cache/        # Cached index results
├── pages/                  # Downloaded HTML pages
│   └── {platform}/{crawl}/ # Organized by platform and crawl
├── requirements.txt
├── AWS_SETUP.md
└── README.md
```

## Step-by-Step Usage

### Step 1: Query the Common Crawl Index

Find URLs for each platform:

```bash
python run_pipeline.py --step index

# Or for a specific crawl
python run_pipeline.py --step index --crawl CC-MAIN-2024-51
```

This creates `data/index_results.json` with all found URLs.

### Step 2: Analyze Page Structure (Optional)

Understand what data is available:

```bash
python analyze_pages.py --platform glovo --sample 10 --extract-test
```

### Step 3: Download HTML Pages

Fetch pages from Common Crawl:

```bash
python run_pipeline.py --step fetch --limit 50  # 50 pages per platform per crawl

# Or fetch all pages
python run_pipeline.py --step fetch
```

Pages are saved to `pages/{platform}/{crawl_id}/`.

### Step 4: Extract Restaurant Data

Parse HTML and create CSV:

```bash
python run_pipeline.py --step extract
```

Output: `data/restaurants_spain.csv`

## Configuration

Edit `code/config.py` to customize:

- **PLATFORMS**: Add or modify platform URL patterns
- **SPANISH_CITIES**: Focus cities for extraction
- **CC_INDEXES**: Which Common Crawl snapshots to process

## Available Crawls

The project includes indexes from 2022-2025:

```
CC-MAIN-2022-05, CC-MAIN-2022-21, CC-MAIN-2022-27, ...
CC-MAIN-2023-06, CC-MAIN-2023-14, ...
CC-MAIN-2024-10, CC-MAIN-2024-18, ...
CC-MAIN-2025-03, CC-MAIN-2025-08, ...
```

Each crawl represents a snapshot of the web taken during that period.

## Data Extraction Details

### Glovo
- URL pattern: `glovoapp.com/es/es/{city}/restaurants...`
- Data sources: JSON-LD, embedded Next.js data, HTML cards

### Uber Eats
- URL pattern: `ubereats.com/es/city/{city}...`
- Data sources: JSON-LD, React Query state, HTML structure

### Just Eat
- URL pattern: `just-eat.es/{city}` or `just-eat.es/area/{city}`
- Data sources: JSON-LD, initial state, HTML cards

## Troubleshooting

### No URLs found in index
- Check that the crawl ID exists
- Platform URL patterns may have changed; update `config.py`

### Empty extractions
- Pages may use client-side rendering not captured by Common Crawl
- Run `analyze_pages.py` to understand page structure
- Update extractors if page format has changed

### AWS connection issues
- Verify credentials are set correctly
- Ensure region is `us-east-1`
- See [AWS_SETUP.md](AWS_SETUP.md)

## Performance Tips

1. **Use AWS credentials** for faster, unrestricted access
2. **Run in US-East** for minimal latency to S3
3. **Process in parallel** using `--workers` flag
4. **Cache index results** (automatic in `data/index_cache/`)

## License

This project is for research and educational purposes. Please respect:
- Common Crawl's terms of service
- Robots.txt restrictions of original sites
- Platform terms of service for data usage
