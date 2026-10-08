"""Polite HTTP fetching: shared session, User-Agent, per-host delay and robots.txt."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from . import __version__

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = f"jobscraper/{__version__} (+https://github.com/gladiola/jobscraper)"


class Fetcher:
    """Thin wrapper around :class:`requests.Session` used by every source."""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 20.0,
        delay: float = 1.0,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.timeout = timeout
        self.delay = delay
        self._last_request: Dict[str, float] = {}
        self._robots: Dict[str, RobotFileParser] = {}

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        wait = self._last_request.get(host, 0.0) + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        self._throttle(url)
        log.debug("GET %s %s", url, params or "")
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.get(url, params=params).json()

    def post_json(self, url: str, payload: Any) -> Any:
        self._throttle(url)
        log.debug("POST %s %s", url, payload)
        response = self.session.post(url, json=payload, timeout=self.timeout, headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()

    def allowed(self, url: str) -> bool:
        """Return True if robots.txt for ``url``'s host permits fetching it."""
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(base)
        if parser is None:
            parser = RobotFileParser()
            try:
                self._throttle(base)
                response = self.session.get(f"{base}/robots.txt", timeout=self.timeout)
                if response.status_code in (401, 403):
                    parser.disallow_all = True
                elif response.status_code >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(response.text.splitlines())
            except requests.RequestException as exc:
                log.debug("Could not fetch robots.txt for %s: %s", base, exc)
                parser.allow_all = True
            self._robots[base] = parser
        return parser.can_fetch(self.user_agent, url)
