"""In-process realtime fan-out (WebSocket hubs)."""

from app.realtime.hub import job_hub

__all__ = ["job_hub"]
