import os

BASE_URL = "https://lom.agc.gov.my"

# DataTables JSON endpoints — one per act type
LISTING_ENDPOINTS = {
    "updated":    f"{BASE_URL}/json-updated-2024.php",
    "revised":    f"{BASE_URL}/json-revised-2024.php",
    "repealed":   f"{BASE_URL}/json-repealed-2024.php",
    "amendment":  f"{BASE_URL}/json-amendment-2024.php",
    "translated": f"{BASE_URL}/json-translated-2024.php",
}

DETAIL_URL    = f"{BASE_URL}/act-detail.php"
SUBSID_URL    = f"{BASE_URL}/json-subsid-2024.php"
PRINCIPAL_URL = f"{BASE_URL}/principal.php"
HOMEPAGE_URL  = BASE_URL

# Rate limiting
# Re-verified against the encrypted listing + signed processFile.php
# endpoints on 2026-09-12 (issue #64): no 429/503 at this pace, so kept
# rather than carried over by habit from the retired endpoints.
REQUEST_DELAY  = 1.5   # seconds between requests
RETRY_DELAYS   = [5, 15, 30, 60]  # successive retry waits in seconds
FETCH_PAGE_SIZE = 100  # DataTables records per page

# Step 3 fetches static files from lom.agc.gov.my/ilims/upload/, not the
# WAF-fronted act-detail.php that REQUEST_DELAY exists for, so it runs
# concurrently instead of sleeping. 8 is a floor the host answered without
# throttling, not a measured ceiling — the 429/503 backoff finds the ceiling.
DOWNLOAD_CONCURRENCY = int(os.getenv("DOWNLOAD_CONCURRENCY", "8"))

# Output paths
DATA_DIR         = "data"
INDEX_FILE       = "data/acts_index.json"
METADATA_DIR     = "data/acts_metadata"
CACHE_DIR        = "data/cache"
CACHE_NAME       = "data/cache/lom_cache"
PDF_EN_DIR       = "data/pdfs/en"
CORPUS_MANIFEST  = "data/pdfs/manifest.json"
CORPUS_ASSET_DIR = "data/pdfs"
CORPUS_SIDECAR_DIR = "data/corpus/sidecars"
CORPUS_EXTRACTION_DIR = "data/corpus/extractions"
CORPUS_COVERAGE_REPORT = "data/corpus/coverage.json"
DOWNLOAD_REPORT  = "data/pdfs/download_report.json"
CHUNKS_EN_DIR    = "data/chunks/en"
EXTRACT_REPORT   = "data/chunks/extract_report.json"
LOG_FILE         = "scraper.log"
