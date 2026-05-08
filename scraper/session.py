import logging
import requests
import requests_cache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scraper.config import CACHE_NAME

logger = logging.getLogger(__name__)

# DataTables parameters that vary per-call but don't affect the data returned.
# Excluding them ensures two calls with the same data params hit the same cache entry.
_IGNORED_PARAMS = [
    "draw",
    # columns[] descriptors — same on every call to a given endpoint
    "columns[0][data]", "columns[0][name]", "columns[0][searchable]", "columns[0][orderable]",
    "columns[0][search][value]", "columns[0][search][regex]",
    "columns[1][data]", "columns[1][name]", "columns[1][searchable]", "columns[1][orderable]",
    "columns[1][search][value]", "columns[1][search][regex]",
    "columns[2][data]", "columns[2][name]", "columns[2][searchable]", "columns[2][orderable]",
    "columns[2][search][value]", "columns[2][search][regex]",
    "columns[3][data]", "columns[3][name]", "columns[3][searchable]", "columns[3][orderable]",
    "columns[3][search][value]", "columns[3][search][regex]",
    "columns[4][data]", "columns[4][name]", "columns[4][searchable]", "columns[4][orderable]",
    "columns[4][search][value]", "columns[4][search][regex]",
    "columns[5][data]", "columns[5][name]", "columns[5][searchable]", "columns[5][orderable]",
    "columns[5][search][value]", "columns[5][search][regex]",
    "columns[6][data]", "columns[6][name]", "columns[6][searchable]", "columns[6][orderable]",
    "columns[6][search][value]", "columns[6][search][regex]",
    "columns[7][data]", "columns[7][name]", "columns[7][searchable]", "columns[7][orderable]",
    "columns[7][search][value]", "columns[7][search][regex]",
    "order[0][column]", "order[0][dir]",
]


def build_session() -> requests_cache.CachedSession:
    session = requests_cache.CachedSession(
        cache_name=CACHE_NAME,
        backend="sqlite",
        expire_after=86400 * 7,           # cache valid for 7 days
        allowable_methods=["GET", "POST"], # must explicitly enable POST caching
        allowable_codes=[200],
        match_headers=False,
        ignored_parameters=_IGNORED_PARAMS,
    )

    retry = Retry(
        total=3,
        backoff_factor=2.0,               # waits: 2s, 4s, 8s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
        # Don't retry on read timeouts — _safe_get/_safe_post handle that with
        # intentional delays. Without this, urllib3 retries 3x internally AND
        # _safe_get retries again on top, burning hours on a single slow act.
        read=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)",
        "Accept": "application/json, text/html, */*",
        "Referer": "https://lom.agc.gov.my/",
    })

    logger.debug("Session created with cache: %s", CACHE_NAME)
    return session
