"""Minimal HTTP plumbing for the read-only Reddit collector."""

from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_USER_AGENT = (
    "nichefinder-reddit-collector/0.1 (read-only public research)"
)


class HttpCollector:
    """Small base class with retries and a shared user agent."""

    source = "http"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )
        self.retries = retries

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def available(self) -> bool:
        """Whether the collector has everything it needs to run."""
        return True

    @property
    def unavailable_reason(self) -> str:
        return f"{self.source} collector is not configured"

    def get_json(self, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url, **kwargs)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"request failed: {url}: {last_error}")

    def collect(self, niche_key: str, query: str) -> Any:  # pragma: no cover
        raise NotImplementedError
