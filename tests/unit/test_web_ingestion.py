from collections.abc import Sequence

import httpx
import pytest

from app.rag.web_ingestion import (
    ContentTooLargeError,
    TooManyRedirectsError,
    UnsafeUrlError,
    UnsupportedWebContentError,
    WebFetchError,
    WebIngestionService,
)


PUBLIC_IP = "93.184.216.34"


async def public_resolver(_: str, __: int) -> Sequence[str]:
    return [PUBLIC_IP]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://user:secret@example.com/",
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://169.254.169.254/latest/meta-data",
    ],
)
async def test_rejects_non_http_credentials_and_non_public_literal_addresses(url: str) -> None:
    service = WebIngestionService(resolver=public_resolver)

    with pytest.raises(UnsafeUrlError):
        await service.ingest(url)


@pytest.mark.asyncio
async def test_rejects_private_or_mixed_dns_answers_before_connecting() -> None:
    requests = 0

    async def unsafe_resolver(_: str, __: int) -> Sequence[str]:
        return [PUBLIC_IP, "10.0.0.5"]

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="never")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=unsafe_resolver)
        with pytest.raises(UnsafeUrlError):
            await service.ingest("https://public.example/page")

    assert requests == 0


@pytest.mark.asyncio
async def test_fetches_through_validated_ip_and_extracts_clean_untrusted_content() -> None:
    observed_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_request
        observed_request = request
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"""
                <html lang="es"><head><title>Guia de algebra</title>
                <style>oculto</style><script>ignorar()</script></head>
                <body><main><h1>Ecuaciones lineales</h1><p>Actividad guiada.</p></main></body></html>
            """,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=public_resolver)
        document = await service.ingest("https://teacher.example/guide#section")

    assert observed_request is not None
    assert observed_request.url.host == PUBLIC_IP
    assert observed_request.headers["host"] == "teacher.example"
    assert observed_request.headers["user-agent"].startswith("AI-Tutor-Claudio/")
    assert document.requested_url == "https://teacher.example/guide"
    assert document.final_url == "https://teacher.example/guide"
    assert document.title == "Guia de algebra"
    assert document.language == "es"
    assert "Ecuaciones lineales" in document.content
    assert "Actividad guiada" in document.content
    assert "ignorar" not in document.content
    assert "oculto" not in document.content
    assert document.trust_level == "UNTRUSTED_EXTERNAL"
    assert document.metadata["instruction_handling"] == "CONTENT_ONLY"
    assert document.metadata["resolved_ips"] == [PUBLIC_IP]


@pytest.mark.asyncio
async def test_revalidates_redirect_destination_and_blocks_ssrf() -> None:
    requested_hosts: list[str] = []

    async def resolver(host: str, _: int) -> Sequence[str]:
        return ["10.0.0.8"] if host == "internal.example" else [PUBLIC_IP]

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_hosts.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "http://internal.example/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=resolver)
        with pytest.raises(UnsafeUrlError):
            await service.ingest("https://public.example/start")

    assert requested_hosts == ["public.example"]


@pytest.mark.asyncio
async def test_follows_a_safe_redirect_and_preserves_logical_final_url() -> None:
    requested_hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        requested_hosts.append(host)
        if host == "first.example":
            return httpx.Response(302, headers={"location": "https://second.example/lesson"})
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-language": "es-MX"},
            text="Contenido final seguro.",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=public_resolver)
        document = await service.ingest("https://first.example/start")

    assert requested_hosts == ["first.example", "second.example"]
    assert document.final_url == "https://second.example/lesson"
    assert document.metadata["redirect_count"] == 1
    assert document.language == "es-MX"


@pytest.mark.asyncio
async def test_enforces_redirect_limit() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=public_resolver, max_redirects=0)
        with pytest.raises(TooManyRedirectsError):
            await service.ingest("https://loop.example/start")


@pytest.mark.asyncio
async def test_enforces_declared_and_streamed_size_limits() -> None:
    async def declared_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain", "content-length": "100"},
            stream=httpx.ByteStream(b"small"),
        )

    async def streamed_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"too large")

    async with httpx.AsyncClient(transport=httpx.MockTransport(declared_handler)) as client:
        with pytest.raises(ContentTooLargeError):
            await WebIngestionService(
                client=client, resolver=public_resolver, max_bytes=8
            ).ingest("https://size.example/")
    async with httpx.AsyncClient(transport=httpx.MockTransport(streamed_handler)) as client:
        with pytest.raises(ContentTooLargeError):
            await WebIngestionService(
                client=client, resolver=public_resolver, max_bytes=8
            ).ingest("https://size.example/")


@pytest.mark.asyncio
async def test_rejects_non_text_content_type() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"pdf")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=public_resolver)
        with pytest.raises(UnsupportedWebContentError):
            await service.ingest("https://files.example/manual.pdf")


@pytest.mark.asyncio
async def test_converts_transport_timeout_to_controlled_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = WebIngestionService(client=client, resolver=public_resolver)
        with pytest.raises(WebFetchError, match="tiempo límite"):
            await service.ingest("https://slow.example/")
