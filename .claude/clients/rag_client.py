"""HTTP client for the private local RAG service.

The client is the only layer under `.claude/clients` that knows the RAG HTTP
contract. Agent tools should call this class instead of talking directly to the
RAG API, embedding model, or PostgreSQL database.
"""

from __future__ import annotations

import json
import socket
from json import JSONDecodeError
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config


JsonObject = dict[str, Any]
UrlOpener = Callable[..., Any]


class RagClientError(RuntimeError):
    """A local RAG request failed with an actionable message."""


class RagClient:
    """Small synchronous client for the local RAG API."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        opener: UrlOpener | None = None,
    ) -> None:
        resolved_url = base_url or config.RAG_API_BASE_URL
        self.base_url = resolved_url.rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else config.RAG_API_TIMEOUT_SECONDS
        )
        self._opener = opener or urlopen

        if not self.base_url:
            raise ValueError("RAG base URL cannot be empty")
        if self.timeout_seconds <= 0:
            raise ValueError(
                "RAG timeout_seconds must be positive"
            )

    def ready(self) -> JsonObject:
        """Return the RAG readiness response."""
        return self._request("GET", "/ready")

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        candidate_k: int = 40,
        source_types: list[str] | None = None,
        source_keys: list[str] | None = None,
    ) -> JsonObject:
        """Search the local RAG index and return its JSON response."""
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError("query cannot be blank")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if not 5 <= candidate_k <= 200:
            raise ValueError(
                "candidate_k must be between 5 and 200"
            )
        if candidate_k < top_k:
            raise ValueError(
                "candidate_k must be greater than or equal to top_k"
            )

        payload: JsonObject = {
            "query": normalized_query,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "source_types": list(source_types or []),
            "source_keys": list(source_keys or []),
        }

        response = self._request(
            "POST",
            "/v1/search",
            payload,
        )
        self._validate_search_response(response)
        return response

    def _request(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        body = None
        headers = {
            "Accept": "application/json",
        }

        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")
            headers["Content-Type"] = (
                "application/json; charset=utf-8"
            )

        request = Request(
            url=f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with self._opener(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            message = self._read_http_error(exc)
            raise RagClientError(
                f"RAG API returned HTTP {exc.code}: {message}"
            ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise RagClientError(
                "Cannot reach the local RAG API at "
                f"{self.base_url}. Start the RAG server and "
                "confirm that GET /ready returns status=ok."
            ) from exc

        try:
            parsed = json.loads(raw_body)
        except JSONDecodeError as exc:
            raise RagClientError(
                "RAG API returned invalid JSON"
            ) from exc

        if not isinstance(parsed, dict):
            raise RagClientError(
                "RAG API returned an unexpected JSON value"
            )

        return parsed

    @staticmethod
    def _read_http_error(exc: HTTPError) -> str:
        try:
            raw_body = exc.read().decode("utf-8")
            parsed = json.loads(raw_body)
            if isinstance(parsed, dict):
                return str(
                    parsed.get("message")
                    or parsed.get("detail")
                    or "request failed"
                )
        except Exception:
            pass
        return exc.reason or "request failed"

    @staticmethod
    def _validate_search_response(
        response: JsonObject,
    ) -> None:
        required_fields = {
            "results",
            "result_count",
            "embedding_model",
            "elapsed_ms",
        }
        missing_fields = required_fields.difference(response)

        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise RagClientError(
                f"RAG search response is missing: {missing}"
            )
        if not isinstance(response["results"], list):
            raise RagClientError(
                "RAG search response results must be a list"
            )
        if response["result_count"] != len(response["results"]):
            raise RagClientError(
                "RAG search result_count does not match results"
            )