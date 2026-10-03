"""Bounded HTTPS import with pinned public addresses and validated redirects."""

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.services.object_storage import MAX_UNDERLAG_BYTES


class SourceImportError(ValueError):
    pass


async def public_endpoint(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise SourceImportError("source_url_requires_public_https")
    host = parsed.hostname.encode("idna").decode()
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceImportError("source_host_not_found") from exc
    ips = sorted({address[4][0] for address in addresses})
    if not ips or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in ips):
        raise SourceImportError("private_source_url_denied")
    # DNS is checked once. Connecting to the checked IP prevents DNS rebinding.
    ip = ips[0]
    authority = f"[{ip}]" if ":" in ip else ip
    endpoint = urlunsplit(("https", authority, parsed.path or "/", parsed.query, ""))
    return endpoint, host


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif not self.hidden and tag in {"p", "div", "br", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


async def fetch_source_url(url: str) -> tuple[bytes, str, str, str]:
    """Return bytes, MIME, filename, final original URL; never follows unchecked redirects."""
    current = url
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
        for redirect in range(4):
            endpoint, host = await public_endpoint(current)
            # httpcore uses this extension for TLS certificate verification/SNI.
            async with client.stream("GET", endpoint, headers={"Host": host, "Accept": "text/plain,text/html,application/pdf"},
                                     extensions={"sni_hostname": host}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if redirect == 3 or not location:
                        raise SourceImportError("source_redirect_limit")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and (not length.isdigit() or int(length) > MAX_UNDERLAG_BYTES):
                    raise SourceImportError("source_too_large")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_UNDERLAG_BYTES:
                        raise SourceImportError("source_too_large")
                    chunks.append(chunk)
                content = b"".join(chunks)
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                name = urlsplit(current).path.rsplit("/", 1)[-1] or "source"
                if mime == "text/html":
                    parser = _PageText()
                    parser.feed(content.decode(response.encoding or "utf-8", errors="replace"))
                    content = "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip()).encode()
                    mime, name = "text/plain", f"{name}.txt"
                elif mime in {"text/plain", "text/markdown"}:
                    name += ".md" if mime == "text/markdown" else ".txt"
                elif mime == "application/pdf":
                    name += "" if name.lower().endswith(".pdf") else ".pdf"
                elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    name += "" if name.lower().endswith(".docx") else ".docx"
                else:
                    raise SourceImportError("unsupported_source_url_content_type")
                if not content:
                    raise SourceImportError("empty_source_url")
                return content, mime, name[:255], current
    raise SourceImportError("source_redirect_limit")
