"""URL imports are bounded and cannot redirect or rebind into private networks."""

import socket

import httpx
import pytest

from app.services.workspace import url_ingest


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://example.test/file", "https://user:pw@example.test/file", "https://example.test:444/file"])
async def test_url_requires_public_https(url):
    with pytest.raises(url_ingest.SourceImportError, match="public_https"):
        await url_ingest.public_endpoint(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.4.2.1", "169.254.169.254", "::1", "fd00::1", "224.0.0.1"])
async def test_url_rejects_private_and_multicast_dns(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kw: [(None, None, None, None, (address, 443))])
    with pytest.raises(url_ingest.SourceImportError, match="private_source"):
        await url_ingest.public_endpoint("https://example.test/source")


def mock_client(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(url_ingest.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_import_pins_verified_ip_and_preserves_tls_hostname(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kw: [(None, None, None, None, ("93.184.216.34", 443))])
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Evidence</p><script>private script</script>")
    mock_client(monkeypatch, handler)
    raw, mime, _name, final_url = await url_ingest.fetch_source_url("https://example.test/source")
    assert raw == b"Evidence" and mime == "text/plain" and final_url == "https://example.test/source"
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.test"
    assert requests[0].extensions["sni_hostname"] == "example.test"


@pytest.mark.asyncio
async def test_redirect_is_validated_before_private_request(monkeypatch):
    def resolve(host, *_args, **_kw):
        return [(None, None, None, None, ("127.0.0.1" if host == "internal.test" else "93.184.216.34", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://internal.test/secret"})
    mock_client(monkeypatch, handler)
    with pytest.raises(url_ingest.SourceImportError, match="private_source"):
        await url_ingest.fetch_source_url("https://example.test/source")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_download_has_enforced_byte_limit(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kw: [(None, None, None, None, ("93.184.216.34", 443))])
    monkeypatch.setattr(url_ingest, "MAX_UNDERLAG_BYTES", 4)
    mock_client(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"12345"))
    with pytest.raises(url_ingest.SourceImportError, match="source_too_large"):
        await url_ingest.fetch_source_url("https://example.test/source")
