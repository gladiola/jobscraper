import json

import pytest
import requests

from jobscraper.fetch import Fetcher


class FakeResponse:
    def __init__(self, body="", status=200, content_type="text/html"):
        self._body = body
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    def json(self):
        return self._body if not isinstance(self._body, str) else json.loads(self._body)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeSession:
    """Minimal stand-in for requests.Session: maps URLs to canned responses."""

    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._respond(self.routes.get(url), params)

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append(("POST " + url, json))
        return self._respond(self.routes.get("POST " + url), json)

    def _respond(self, route, params):
        if route is None:
            return FakeResponse("not found", status=404)
        if callable(route):
            route = route(params)
        if isinstance(route, FakeResponse):
            return route
        if isinstance(route, str):
            return FakeResponse(route)
        return FakeResponse(route, content_type="application/json")


@pytest.fixture
def make_fetcher():
    def factory(routes):
        return Fetcher(session=FakeSession(routes), delay=0)
    return factory
