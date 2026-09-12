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


_DEFAULT_FORCELIST = [429, 500, 502, 503, 504]

# Empty on purpose. _download_pdf owns the download retry schedule, including
# the 429/503 back-off that shrinks concurrency, and a second layer underneath
# it is invisible to that back-off: urllib3 would quietly spend four requests
# per call before _download_pdf ever sees the 429. The AGC asset host also
# answers a missing file with 500 and an HTML body rather than 404, which
# _download_pdf tells apart by Content-Type and never retries.
_DOWNLOAD_FORCELIST: list[int] = []


def _retry_adapter(*, status_forcelist: list[int] | None = None) -> HTTPAdapter:
    """None means the shared default; an empty list disables status retries.

    read stays False everywhere. With a read budget urllib3 turns an exhausted
    read timeout into MaxRetryError, which requests raises as ConnectionError,
    so the caller's `except Timeout` never fires and one attempt silently costs
    two full read timeouts.
    """
    retry = Retry(
        total=3,
        backoff_factor=2.0,
        status_forcelist=_DEFAULT_FORCELIST if status_forcelist is None else status_forcelist,
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
        read=False,
    )
    return HTTPAdapter(max_retries=retry)


def build_download_session() -> requests.Session:
    """Plain (uncached) session for binary downloads — avoids storing PDFs in SQLite.

    Not thread-safe. Step 3 builds one of these per pool worker rather than
    sharing one, so the default pool_maxsize of 10 is ample for each.
    """
    session = requests.Session()
    adapter = _retry_adapter(status_forcelist=_DOWNLOAD_FORCELIST)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)",
        "Accept": "application/pdf, */*",
        "Referer": "https://lom.agc.gov.my/",
    })
    return session


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

    adapter = _retry_adapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)",
        "Accept": "application/json, text/html, */*",
        "Referer": "https://lom.agc.gov.my/",
    })

    logger.debug("Session created with cache: %s", CACHE_NAME)
    return session
