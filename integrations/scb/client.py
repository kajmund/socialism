"""Thin async client for SCB PxWebApi 2."""

from __future__ import annotations

import os
from typing import Any, TypedDict

import httpx

DEFAULT_BASE_URL = "https://statistikdatabasen.scb.se/api/v2"


class VariableSelection(TypedDict, total=False):
    variableCode: str
    valueCodes: list[str]
    codelist: str


class ScbClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = (base_url or os.environ.get("SCB_API_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self._timeout = timeout

    async def search_tables(
        self,
        query: str,
        *,
        lang: str = "sv",
        page_size: int = 20,
        page_number: int = 1,
        include_discontinued: bool = False,
    ) -> dict[str, Any]:
        params = {
            "query": query.strip(),
            "lang": lang,
            "pageSize": max(1, min(page_size, 100)),
            "pageNumber": max(1, page_number),
            "includeDiscontinued": str(include_discontinued).lower(),
        }
        return await self._get("/tables", params=params)

    async def get_table(self, table_id: str, *, lang: str = "sv") -> dict[str, Any]:
        return await self._get(f"/tables/{table_id.strip()}", params={"lang": lang})

    async def get_table_meta(self, table_id: str, *, lang: str = "sv") -> dict[str, Any]:
        return await self._get(f"/tables/{table_id.strip()}/metadata", params={"lang": lang})

    async def query(
        self,
        table_id: str,
        filters: list[VariableSelection],
        *,
        lang: str = "sv",
        output_format: str = "json-stat2",
    ) -> dict[str, Any]:
        body = {"selection": filters}
        params = {"lang": lang, "outputFormat": output_format}
        return await self._post(f"/tables/{table_id.strip()}/data", params=params, json=body)

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    async def _post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            response = await client.post(path, params=params, json=json)
            response.raise_for_status()
            return response.json()
