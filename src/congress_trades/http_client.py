"""A polite HTTP client shared by every extractor.

It identifies itself with the configured User-Agent, waits between requests
to the same host, and retries transient failures with backoff. Government
sites are slow and occasionally flaky; a retry is cheaper than a failed run.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class PoliteSession(requests.Session):
    def __init__(self, user_agent: str, delay: float = 0.5, timeout: float = 60):
        super().__init__()
        self.headers["User-Agent"] = user_agent
        self.delay = delay
        self.timeout = timeout
        self._last: dict[str, float] = {}
        retry = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.mount("https://", adapter)
        self.mount("http://", adapter)

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        host = urlparse(url).netloc
        wait = self.delay - (time.monotonic() - self._last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        kwargs.setdefault("timeout", self.timeout)
        try:
            return super().request(method, url, *args, **kwargs)
        finally:
            self._last[host] = time.monotonic()
