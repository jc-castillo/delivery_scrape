# Delivery Scrape

Extract restaurant data from Spanish food delivery platforms (Glovo, Just Eat, Uber Eats) using Common Crawl archives.

## Directory Structure

```
code/           Python pipeline code
  config.py     Crawl IDs, platform definitions, paths
  cc_athena.py  Query Common Crawl index via AWS Athena
  cc_fetch.py   Download HTML from WARC files
  extract_data.py  Extract restaurants from HTML, deduplicate, save
  extractors/   Per-platform extraction logic (base, glovo, justeat, ubereats)
  run_pipeline.py  Orchestrator (--step index|fetch|extract, --crawl ID)
  verify_step*.py  Verification scripts (3 steps)
data/           Output data
  index_cache/  Athena query results cached as JSON
  restaurants/  Per-crawl/platform CSV and Parquet files
  restaurants_spain.csv          Combined output
  restaurants_spain.summary.json Summary stats
pages/          Downloaded HTML files
  {platform}/{crawl_id}/         One dir per platform+crawl combo
    {hash}.html + {hash}.json    HTML content + metadata sidecar
logs/           Pipeline logs
```

## Key Conventions

- **Crawl ID format**: `CC-MAIN-YYYY-WW` (e.g., `CC-MAIN-2024-33`)
- **Platform keys**: `glovo`, `justeat`, `ubereats` (in code/dirs); display names: `Glovo`, `Just Eat`, `Uber Eats`
- **All valid crawl IDs** are listed in `code/config.py` → `CC_INDEXES`
- **Deduplication** uses `(restaurant_url, crawl_id)` as the primary key
- **Extractors** inherit from `BaseExtractor` in `code/extractors/base.py`

## Adding a New Crawl

### Step 1: Verify the crawl ID exists in `CC_INDEXES` (code/config.py)

### Step 2: Index + Fetch
```bash
python code/run_pipeline.py --step index --crawl CC-MAIN-YYYY-WW
python code/run_pipeline.py --step fetch --crawl CC-MAIN-YYYY-WW
```
This queries Athena for platform URLs, caches results in `data/index_cache/`, then downloads HTML from WARC files into `pages/`.

### Step 3: Extract (processes ALL crawls)
```bash
python code/extract_data.py
```
Extracts restaurants from all HTML files, deduplicates, and saves combined CSV + per-crawl Parquet files.

### Step 4: Verify
```bash
python code/verify_step1_index_vs_html.py   # Index vs HTML consistency
python code/verify_step2_html_vs_extraction.py  # Extraction correctness sampling
python code/verify_step3_data_quality.py     # CSV quality checks
```

## Verification Checklist

- No `MISSING` HTML files (step 1)
- No `MISSING_NAMES` or `ZERO_FROM_LISTING` (step 2)
- No `INTRA_PAGE_DUPES` for new crawls (step 2)
- 0 HTML entities in names, 0 corrupted cities (step 3)
- Reasonable food_type coverage per platform (step 3)

## Running with Agents

Use the agents in `.claude/agents/` to add crawls:
1. `fetch-crawl` — Index + download for a specific crawl
2. `extract-crawl` — Run extraction across all crawls
3. `verify-html` — Verify HTML download integrity
4. `verify-extraction` — Verify extraction quality
