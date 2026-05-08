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
HOMEPAGE_URL  = BASE_URL

# Rate limiting
REQUEST_DELAY  = 1.5   # seconds between requests
RETRY_DELAYS   = [5, 15, 30, 60]  # successive retry waits in seconds
FETCH_PAGE_SIZE = 100  # DataTables records per page

# Output paths
DATA_DIR      = "data"
INDEX_FILE    = "data/acts_index.json"
METADATA_DIR  = "data/acts_metadata"
CACHE_DIR     = "data/cache"
CACHE_NAME    = "data/cache/lom_cache"
LOG_FILE      = "scraper.log"
