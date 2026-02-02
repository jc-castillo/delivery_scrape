# Food Delivery Restaurant Scraper (Spain)

Extract historical restaurant data from Glovo, Uber Eats, and Just Eat in Spain using Common Crawl archives (2022-present).

## Current Data Summary

**180,111 restaurants** extracted across 3 crawls, 3 platforms, and 1,376 cities.

| Crawl | Glovo | Just Eat | Uber Eats | Total |
|-------|-------|----------|-----------|-------|
| CC-MAIN-2022-05 | 28,697 | 5,880 | 6,477 | 41,054 |
| CC-MAIN-2023-40 | 41,011 | 10,180 | 5,479 | 56,670 |
| CC-MAIN-2024-51 | 47,639 | 24,790 | 9,958 | 82,387 |
| **Total** | **117,347** | **40,850** | **21,914** | **180,111** |

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Set Up AWS

AWS credentials are required for Athena queries and faster S3 access:

```bash
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"
```

See [AWS_SETUP.md](AWS_SETUP.md) for detailed instructions.

### 3. Run the Pipeline for a New Crawl

```bash
cd code

# Process a single crawl (recommended for testing)
python run_pipeline.py --all --crawl CC-MAIN-2025-08

# Process multiple crawls
python run_pipeline.py --all --crawl CC-MAIN-2025-08 --crawl CC-MAIN-2025-03

# Process all crawls defined in config.py
python run_pipeline.py --all
```

## Adding a New Crawl

### Step 1: Find the Crawl ID

Common Crawl IDs follow the format `CC-MAIN-YYYY-WW` where:
- `YYYY` = year
- `WW` = crawl number within the year

Find available crawls at: https://commoncrawl.org/overview

### Step 2: Run the Pipeline

```bash
cd code
python run_pipeline.py --all --crawl CC-MAIN-2025-XX
```

This will:
1. **Index** - Query Athena to find all platform URLs in that crawl (~2-5 min)
2. **Fetch** - Download HTML pages from Common Crawl WARC files (~10-30 min depending on page count)
3. **Extract** - Parse HTML and extract restaurant data (~5-10 min)

### Step 3: Verify Results

Check the output summary printed at the end, or view the files:

```bash
# View the summary
cat data/restaurants_spain.summary.json | python -m json.tool

# Count restaurants per platform
cd data/restaurants
ls -la *.csv
```

## Pipeline Commands

### Full Pipeline

```bash
# Run all steps for specific crawl(s)
python run_pipeline.py --all --crawl CC-MAIN-2025-08

# Run all steps for all configured crawls
python run_pipeline.py --all

# Limit pages per platform (for testing)
python run_pipeline.py --all --crawl CC-MAIN-2025-08 --limit 100
```

### Individual Steps

```bash
# Step 1: Query Common Crawl index (find URLs)
python run_pipeline.py --step index --crawl CC-MAIN-2025-08

# Step 2: Fetch HTML pages from WARC files
python run_pipeline.py --step fetch --crawl CC-MAIN-2025-08

# Step 3: Extract restaurant data
python run_pipeline.py --step extract
```

### Options

| Flag | Description |
|------|-------------|
| `--all` | Run all pipeline steps |
| `--step {index,fetch,extract}` | Run a specific step |
| `--crawl CC-MAIN-YYYY-WW` | Process specific crawl (can be repeated) |
| `--limit N` | Limit pages per platform per crawl |
| `--workers N` | Parallel workers for fetching (default: 10) |
| `--no-cache` | Re-run Athena queries (ignore cached index results) |
| `--all-pages` | Fetch all page types (not just listing pages) |
| `--output PATH` | Custom output CSV path |

## Project Structure

```
delivery_scrape/
├── code/
│   ├── run_pipeline.py     # Main orchestration script
│   ├── config.py           # Configuration (platforms, crawl IDs)
│   ├── cc_athena.py        # Athena index queries
│   ├── cc_fetch.py         # WARC file fetching
│   ├── extract_data.py     # Data extraction
│   └── extractors/         # Platform-specific extractors
│       ├── base.py         # Base extractor class
│       ├── glovo.py        # Glovo extraction
│       ├── ubereats.py     # Uber Eats extraction
│       └── justeat.py      # Just Eat extraction
├── data/
│   ├── index_cache/        # Cached Athena query results
│   ├── restaurants/        # Per-crawl/platform CSV+Parquet files
│   ├── restaurants_spain.csv           # Combined CSV
│   └── restaurants_spain.summary.json  # Summary statistics
├── pages/                  # Downloaded HTML pages
│   └── {url-based-structure}/
├── requirements.txt
├── AWS_SETUP.md
└── README.md
```

## Output Data

### Combined CSV: `data/restaurants_spain.csv`

| Column | Description |
|--------|-------------|
| `name` | Restaurant name |
| `platform` | Glovo, Just Eat, or Uber Eats |
| `city` | Spanish city |
| `date` | Snapshot date (YYYY-MM-DD) |
| `address` | Street address (when available) |
| `food_type` | Primary cuisine type |
| `categories` | All cuisine categories (pipe-separated) |
| `rating` | Restaurant rating (1-5 scale) |
| `num_ratings` | Number of ratings |
| `price_range` | Price category |
| `delivery_fee` | Delivery cost |
| `delivery_time` | Estimated delivery time |
| `restaurant_url` | Link to restaurant page |
| `source_url` | Original Common Crawl URL |
| `crawl_id` | Common Crawl snapshot ID |

### Per-Crawl Files: `data/restaurants/{crawl_id}_{platform}.csv`

Same columns, split by crawl and platform for easier analysis.

## Platform Extraction Details

### Glovo
- **Domain**: glovoapp.com
- **URL pattern**: `/es/{lang}/{city}/restaurantes...`
- **Data sources**: HTML store cards, JSON-LD

### Uber Eats
- **Domain**: ubereats.com
- **URL pattern**: `/es/city/{city}...`
- **Data sources**: JSON-LD, React Query state

### Just Eat
- **Domain**: just-eat.es
- **URL pattern**: `/area/{postal_code}-{city}`
- **Data sources**: JSON-LD, HTML restaurant cards

## Configuration

Edit `code/config.py` to customize:

- `PLATFORMS` - URL patterns for each platform
- `CC_INDEXES` - List of all available crawl IDs
- `TEST_CRAWLS` - Subset of crawls for testing

## Troubleshooting

### "No URLs found in index"
- Verify the crawl ID exists and is complete
- Check Athena console for query errors
- The crawl may not have captured the platform

### "Empty extractions"
- Some pages use client-side rendering not captured by Common Crawl
- Page structure may have changed; check HTML manually
- Run with `--limit 10` and inspect downloaded files

### AWS/Athena errors
- Verify credentials: `aws sts get-caller-identity`
- Ensure region is `us-east-1`
- Check S3 bucket permissions for query output

### Re-running a crawl
- Delete cached index: `rm data/index_cache/{crawl_id}_*.json`
- Delete downloaded pages: `rm -rf pages/*/{crawl_id}`
- Re-run: `python run_pipeline.py --all --crawl {crawl_id} --no-cache`

## Performance Tips

1. **Run in US-East** - Minimal latency to Common Crawl S3
2. **Use parallel workers** - `--workers 20` for faster fetching
3. **Cache is your friend** - Index results are cached automatically
4. **Start small** - Test with `--limit 50` before full runs

## License

This project is for research and educational purposes. Please respect:
- Common Crawl's terms of service
- Platform terms of service for data usage
