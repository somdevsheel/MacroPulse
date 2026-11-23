"""Shared HTTP client with retry/backoff and rate-limit awareness.

Retries on network errors, HTTP 429 and 5xx with exponential backoff (honouring Retry-After).
URLs are logged with secrets redacted.
"""

import logging
import re

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)
# httpx logs full request URLs (with api_key=...) at INFO. Keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

# `c=` is Trading Economics' credential parameter.
_SECRET_PARAMS = re.compile(
    r"(?<![A-Za-z0-9_])(api_key|apikey|token|key|c)=([^&\s]+)", re.IGNORECASE
)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def redact(url: str) -> str:
    return _SECRET_PARAMS.sub(r"\1=***", url)


class RetryableHTTPError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} for {redact(url)}")
        self.status = status


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, RetryableHTTPError | httpx.TransportError)


def make_client(timeout: float = 30.0, user_agent: str = "MacroPulse/0.1") -> httpx.Client:
    return httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})


def get_with_retry(
    client: httpx.Client, url: str, params: dict | None = None, attempts: int = 5
) -> httpx.Response:
    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        reraise=True,
    )
    def _do() -> httpx.Response:
        resp = client.get(url, params=params)
        if resp.status_code in RETRYABLE_STATUS:
            log.warning("retryable HTTP %s from %s", resp.status_code, redact(str(resp.url)))
            raise RetryableHTTPError(resp.status_code, str(resp.url))
        return resp

    return _do()
