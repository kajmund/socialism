"""Record gateway failure details without changing the client's request behavior."""

import httpx

from app.jev.system import HttpJevSystemOne


class DiagnosticJev(HttpJevSystemOne):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[dict] = []

    async def _post(self, body: dict, api_key: str, timeout_seconds: float) -> httpx.Response:
        response = await super()._post(body, api_key, timeout_seconds)
        if response.status_code >= 400:
            self.errors.append({
                "status": response.status_code,
                "message": response.text.replace(api_key, "[redacted]")[:500],
                "limit_headers": {k: v for k, v in response.headers.items()
                    if any(part in k.lower() for part in ("ratelimit", "rate-limit", "retry-after"))},
            })
        return response
