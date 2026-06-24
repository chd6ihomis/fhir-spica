"""Async HTTP clients for FHIR transactional, terminology, and PSA servers.

Every request is timed and recorded in the in-memory logstore so the developer
debugging suite can display raw request/response pairs.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx

from . import logstore
from .config import EffectiveConfig, get_config

FHIR_JSON = "application/fhir+json"
JSON_PATCH = "application/json-patch+json"


class FHIRError(Exception):
    """Raised when a FHIR/PSA call fails. Carries any OperationOutcome body."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _parse_body(response: httpx.Response) -> Any:
    text = response.text
    ctype = response.headers.get("content-type", "")
    if "json" in ctype:
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return text
    return text


async def _request(
    target: str,
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    content: Optional[str] = None,
    timeout: float = 30.0,
) -> Any:
    log_body = content
    try:
        with logstore.Timer() as timer:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method, url, headers=headers, content=content
                )
        body = _parse_body(response)
        logstore.record(
            target=target,
            method=method,
            url=url,
            request_headers=headers,
            request_body=log_body,
            status_code=response.status_code,
            response_headers=dict(response.headers),
            response_body=body,
            duration_ms=timer.elapsed_ms,
        )
        if response.status_code >= 400:
            raise FHIRError(
                f"{method} {url} returned HTTP {response.status_code}",
                status_code=response.status_code,
                body=body,
            )
        return body
    except httpx.HTTPError as exc:
        logstore.record(
            target=target,
            method=method,
            url=url,
            request_headers=headers,
            request_body=log_body,
            error=str(exc),
        )
        raise FHIRError(f"Network error calling {url}: {exc}") from exc


class FHIRClient:
    """Thin async wrapper around the FHIR transactional server."""

    def __init__(self, config: Optional[EffectiveConfig] = None) -> None:
        self.config = config or get_config()
        self.base_url = self.config.fhir_base_url

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers = {"Accept": FHIR_JSON}
        if content_type:
            headers["Content-Type"] = content_type
        if self.config.fhir_auth_token:
            headers["Authorization"] = f"Bearer {self.config.fhir_auth_token}"
        return headers

    async def capability(self) -> Any:
        return await _request(
            "fhir",
            "GET",
            f"{self.base_url}/metadata",
            headers=self._headers(),
            timeout=self.config.http_timeout,
        )

    async def search(self, resource_type: str, params: str = "") -> Any:
        url = f"{self.base_url}/{resource_type}"
        if params:
            url = f"{url}?{params}"
        return await _request(
            "fhir", "GET", url, headers=self._headers(),
            timeout=self.config.http_timeout,
        )

    async def read(self, resource_type: str, resource_id: str) -> Any:
        return await _request(
            "fhir",
            "GET",
            f"{self.base_url}/{resource_type}/{resource_id}",
            headers=self._headers(),
            timeout=self.config.http_timeout,
        )

    async def transaction(self, bundle: Dict[str, Any]) -> Any:
        return await _request(
            "fhir",
            "POST",
            f"{self.base_url}",
            headers=self._headers(FHIR_JSON),
            content=json.dumps(bundle),
            timeout=self.config.http_timeout,
        )

    async def update(self, resource_type: str, resource_id: str, resource: Dict[str, Any]) -> Any:
        return await _request(
            "fhir",
            "PUT",
            f"{self.base_url}/{resource_type}/{resource_id}",
            headers=self._headers(FHIR_JSON),
            content=json.dumps(resource),
            timeout=self.config.http_timeout,
        )

    async def create(self, resource_type: str, resource: Dict[str, Any]) -> Any:
        return await _request(
            "fhir",
            "POST",
            f"{self.base_url}/{resource_type}",
            headers=self._headers(FHIR_JSON),
            content=json.dumps(resource),
            timeout=self.config.http_timeout,
        )

    async def patch(self, resource_type: str, resource_id: str, patch_ops: list) -> Any:
        return await _request(
            "fhir",
            "PATCH",
            f"{self.base_url}/{resource_type}/{resource_id}",
            headers=self._headers(JSON_PATCH),
            content=json.dumps(patch_ops),
            timeout=self.config.http_timeout,
        )

    async def send_module(
        self, method: str, url: str, resource: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute a single granular module operation.

        ``url`` is the relative FHIR path/query exactly as carried on a module
        descriptor, e.g. ``Patient?identifier=system|value`` (conditional PUT
        upsert) or ``ServiceRequest`` (POST create). Absolute URLs are passed
        through unchanged.
        """
        method = method.upper()
        full = url if url.startswith("http") else f"{self.base_url}/{url.lstrip('/')}"
        content = json.dumps(resource) if resource is not None else None
        content_type = FHIR_JSON if content is not None else None
        return await _request(
            "fhir",
            method,
            full,
            headers=self._headers(content_type),
            content=content,
            timeout=self.config.http_timeout,
        )

