from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

try:  # Optional: preferred extraction when the project installs it later.
    import trafilatura  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on optional environment package.
    trafilatura = None

try:  # Optional fallback; stdlib extraction remains available for the base MVP.
    from bs4 import BeautifulSoup  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on optional environment package.
    BeautifulSoup = None


USER_AGENT = "AI-Tutor-Claudio/0.1 (+local educational research)"
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})


class WebIngestionError(ValueError):
    """Base error for controlled web-ingestion failures."""


class UnsafeUrlError(WebIngestionError):
    """The URL or one of its resolved addresses is unsafe for server-side access."""


class WebFetchError(WebIngestionError):
    """The remote resource could not be fetched safely."""


class TooManyRedirectsError(WebFetchError):
    pass


class ContentTooLargeError(WebFetchError):
    pass


class UnsupportedWebContentError(WebFetchError):
    pass


class EmptyWebContentError(WebFetchError):
    pass


class AsyncHttpClient(Protocol):
    def build_request(
        self,
        method: str,
        url: str | httpx.URL,
        **kwargs: Any,
    ) -> httpx.Request: ...

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response: ...


DnsResolver = Callable[[str, int], Awaitable[Sequence[str]]]


@dataclass(frozen=True)
class WebDocument:
    requested_url: str
    final_url: str
    title: str
    content: str
    fetched_at: str
    language: str
    content_type: str
    metadata: dict[str, Any]
    trust_level: str = "UNTRUSTED_EXTERNAL"


@dataclass(frozen=True)
class _SafeTarget:
    logical_url: str
    pinned_url: httpx.URL
    host_header: str
    sni_hostname: str
    resolved_ip: str


class WebIngestionService:
    """Fetch and clean public web pages while treating all content as untrusted data.

    DNS is resolved before every request and redirect. The connection URL is pinned to
    a validated public IP while preserving the original Host header and HTTPS SNI,
    preventing a second DNS lookup from redirecting the connection to an internal host.
    """

    def __init__(
        self,
        *,
        client: AsyncHttpClient | None = None,
        resolver: DnsResolver | None = None,
        timeout_seconds: float = 10.0,
        max_redirects: int = 5,
        max_bytes: int = 2 * 1024 * 1024,
        user_agent: str = USER_AGENT,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds debe ser mayor que cero.")
        if max_redirects < 0:
            raise ValueError("max_redirects no puede ser negativo.")
        if max_bytes <= 0:
            raise ValueError("max_bytes debe ser mayor que cero.")
        self._client = client
        self._resolver = resolver or resolve_public_dns
        self._timeout = timeout_seconds
        self._max_redirects = max_redirects
        self._max_bytes = max_bytes
        self._user_agent = user_agent

    async def ingest(self, url: str) -> WebDocument:
        try:
            async with asyncio.timeout(self._timeout):
                if self._client is not None:
                    return await self._ingest_with_client(url, self._client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await self._ingest_with_client(url, client)
        except TimeoutError as exc:
            raise WebFetchError("La consulta web superó el tiempo límite total.") from exc

    async def _ingest_with_client(self, url: str, client: AsyncHttpClient) -> WebDocument:
        requested_url = _normalize_url(url)
        current_url = requested_url
        redirects = 0
        resolved_ips: list[str] = []

        while True:
            target = await self._safe_target(current_url)
            resolved_ips.append(target.resolved_ip)
            response = await self._send(client, target)
            if response.status_code in REDIRECT_STATUS_CODES:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise WebFetchError("La redirección no incluye una URL de destino.")
                if redirects >= self._max_redirects:
                    raise TooManyRedirectsError(
                        f"La página superó el límite de {self._max_redirects} redirecciones."
                    )
                redirects += 1
                current_url = _normalize_url(urljoin(current_url, location))
                continue
            break

        try:
            if response.status_code < 200 or response.status_code >= 300:
                raise WebFetchError(f"La página respondió con HTTP {response.status_code}.")
            content_type = _validate_content_type(response.headers.get("content-type"))
            body = await self._read_limited(response)
            encoding = response.encoding or "utf-8"
            html = body.decode(encoding, errors="replace")
            content, title, document_language = _extract_content(html, content_type)
            if not content:
                raise EmptyWebContentError("La página no contiene texto extraíble.")
            final_url = current_url
            fetched_at = datetime.now(UTC).isoformat()
            language = (
                document_language
                or response.headers.get("content-language", "").split(",", 1)[0].strip()
                or "und"
            )
            title = title or urlsplit(final_url).hostname or "Documento web"
            return WebDocument(
                requested_url=requested_url,
                final_url=final_url,
                title=title,
                content=content,
                fetched_at=fetched_at,
                language=language,
                content_type=content_type,
                metadata={
                    "source_type": "web",
                    "requested_url": requested_url,
                    "final_url": final_url,
                    "redirect_count": redirects,
                    "resolved_ips": resolved_ips,
                    "fetched_at": fetched_at,
                    "content_type": content_type,
                    "trust_level": "UNTRUSTED_EXTERNAL",
                    "instruction_handling": "CONTENT_ONLY",
                },
            )
        finally:
            await response.aclose()

    async def _safe_target(self, url: str) -> _SafeTarget:
        parsed = _validated_parts(url)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            addresses = list(await self._resolver(hostname, port))
        except (OSError, UnicodeError) as exc:
            raise WebFetchError(f"No se pudo resolver el dominio '{hostname}'.") from exc
        if not addresses:
            raise WebFetchError(f"El dominio '{hostname}' no devolvió direcciones IP.")
        validated = [_validate_public_ip(address) for address in addresses]
        selected_ip = str(validated[0])
        logical_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
        pinned_url = httpx.URL(logical_url).copy_with(host=selected_ip)
        return _SafeTarget(
            logical_url=logical_url,
            pinned_url=pinned_url,
            host_header=_host_header(hostname, parsed.port, parsed.scheme),
            sni_hostname=hostname,
            resolved_ip=selected_ip,
        )

    async def _send(self, client: AsyncHttpClient, target: _SafeTarget) -> httpx.Response:
        request = client.build_request(
            "GET",
            target.pinned_url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
                "Host": target.host_header,
            },
            timeout=httpx.Timeout(self._timeout),
            extensions={"sni_hostname": target.sni_hostname},
        )
        try:
            return await client.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise WebFetchError("La consulta web superó el tiempo límite.") from exc
        except httpx.HTTPError as exc:
            raise WebFetchError("No se pudo descargar la página.") from exc

    async def _read_limited(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length:
            try:
                parsed_length = int(declared_length)
            except ValueError:
                parsed_length = None
            if parsed_length is not None and parsed_length > self._max_bytes:
                raise ContentTooLargeError(
                    f"La página supera el límite de {self._max_bytes} bytes."
                )
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise ContentTooLargeError(
                    f"La página supera el límite de {self._max_bytes} bytes."
                )
            chunks.append(chunk)
        return b"".join(chunks)


async def resolve_public_dns(hostname: str, port: int) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    records = await loop.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(record[4][0]) for record in records))


def _normalize_url(url: str) -> str:
    value = url.strip()
    parsed = _validated_parts(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _validated_parts(url: str):
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("La URL contiene un puerto o formato inválido.") from exc
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise UnsafeUrlError("Sólo se permiten URLs HTTP o HTTPS.")
    if not parsed.hostname:
        raise UnsafeUrlError("La URL no contiene un dominio válido.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("No se permiten credenciales dentro de la URL.")
    if "%" in parsed.hostname:
        raise UnsafeUrlError("No se permiten identificadores de zona o escapes en el dominio.")
    try:
        parsed.hostname.encode("idna")
    except UnicodeError as exc:
        raise UnsafeUrlError("El dominio no es válido.") from exc
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        _validate_public_ip(str(literal))
    return parsed


def _validate_public_ip(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError as exc:
        raise UnsafeUrlError("La resolución DNS devolvió una dirección inválida.") from exc
    if (
        not ip.is_global
        or ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise UnsafeUrlError(f"La dirección resuelta para la URL no es pública: {ip}.")
    return ip


def _host_header(hostname: str, explicit_port: int | None, scheme: str) -> str:
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    return f"{host}:{explicit_port}" if explicit_port and explicit_port != default_port else host


def _validate_content_type(raw_content_type: str | None) -> str:
    content_type = (raw_content_type or "").split(";", 1)[0].strip().casefold()
    if content_type not in ALLOWED_CONTENT_TYPES:
        shown = content_type or "no declarado"
        raise UnsupportedWebContentError(f"Tipo de contenido web no permitido: {shown}.")
    return content_type


def _extract_content(raw: str, content_type: str) -> tuple[str, str, str]:
    if content_type == "text/plain":
        return _normalize_text(raw), "", ""

    title = ""
    language = ""
    if trafilatura is not None:
        try:
            extracted = trafilatura.extract(
                raw,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
        except Exception:  # Optional extractor failure must not bypass safe fallbacks.
            extracted = None
        if extracted:
            content = _normalize_text(extracted)
            fallback = _StdlibHtmlExtractor()
            fallback.feed(raw)
            return content, fallback.title, fallback.language

    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw, "html.parser")
        html_element = soup.find("html")
        language = str(html_element.get("lang", "")).strip() if html_element else ""
        title = _normalize_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        for element in soup(["script", "style", "noscript", "template", "svg"]):
            element.decompose()
        return _normalize_text(soup.get_text("\n", strip=True)), title, language

    fallback = _StdlibHtmlExtractor()
    fallback.feed(raw)
    fallback.close()
    return fallback.content, fallback.title, fallback.language


def _normalize_text(value: str) -> str:
    return "\n".join(line for line in (" ".join(part.split()) for part in value.splitlines()) if line)


class _StdlibHtmlExtractor(HTMLParser):
    _IGNORED_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
    _BLOCK_TAGS = frozenset(
        {"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "main", "p", "section"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._ignored_depth = 0
        self._in_title = False
        self.language = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        attributes = dict(attrs)
        if normalized == "html" and attributes.get("lang"):
            self.language = str(attributes["lang"]).strip()
        if normalized in self._IGNORED_TAGS:
            self._ignored_depth += 1
        elif normalized == "title":
            self._in_title = True
        elif normalized in self._BLOCK_TAGS and self._parts:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif normalized == "title":
            self._in_title = False
        elif normalized in self._BLOCK_TAGS and self._parts:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._parts.append(data)

    @property
    def title(self) -> str:
        return _normalize_text(" ".join(self._title_parts))

    @property
    def content(self) -> str:
        return _normalize_text("".join(self._parts))
