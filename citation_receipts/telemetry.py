"""Low-cardinality structured observability for receipt lifecycle outcomes."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("citation_receipts.telemetry")


def record(event: str, **fields: Any) -> None:
    safe = {key: value for key, value in fields.items() if value not in {None, ""}}
    logger.info(json.dumps({"event": event, **safe}, sort_keys=True, ensure_ascii=True))
