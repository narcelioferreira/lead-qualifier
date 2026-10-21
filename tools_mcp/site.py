"""`fetch_company_site`: home e página "sobre" da empresa, extraídas com trafilatura.

**SSRF:** o domínio vem do lead. Além da validação do `LeadInput`, cada requisição (e cada
salto de redirect) só segue se o host resolver exclusivamente para IPs públicos, na porta
80/443. Risco residual: DNS rebinding entre a checagem e a conexão; a mitigação completa
(conectar no IP checado) fica para o container isolado de tools (T19/T20).

O conteúdo dos sites é **não confiável**: sai sanitizado e truncado, e o prompt que o consome
deve delimitá-lo. Domínios `.example` (empresas fictícias) são servidos pelas fixtures da
avaliação, sem rede.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from lxml import etree
from lxml import html as lxml_html
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas import normalize_domain, sanitize_text
from tools_mcp.base import ToolCache, ToolRequestError, cache_key

TOOL = "fetch_company_site"
MAX_PAGE_CHARS = 4000
MAX_HTML_BYTES = 2_000_000
MAX_REDIRECTS = 5
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
SIMULATED_TLD = ".example"
# Header HTTP só aceita ASCII.
USER_AGENT = "lead-qualifier/0.1 (pesquisa de dados publicos de empresas; projeto academico)"

# Links que costumam levar à página institucional.
_ABOUT = re.compile(
    r"(sobre|quem[-_ ]?somos|about|a[-_ ]?empresa|institucional|nossa[-_ ]?hist[oó]ria)",
    re.IGNORECASE,
)

Resolver = Callable[[str], Awaitable[list[str]]]


class SitePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["home", "about"]
    url: HttpUrl
    text: str = Field(max_length=MAX_PAGE_CHARS)


class SiteContent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str
    pages: list[SitePage]
    errors: list[str] = Field(default_factory=list)
    simulated: bool = False
    retrieved_at: datetime
    cached: bool = False


class _FetchError(Exception):
    pass


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


class SiteFetcher:
    def __init__(
        self,
        cache: ToolCache,
        *,
        fixtures_dir: Path | None = None,
        resolver: Resolver = system_resolver,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cache = cache
        self._fixtures_dir = fixtures_dir
        self._resolver = resolver
        self._timeout = timeout
        self._transport = transport

    async def fetch(self, domain: str) -> SiteContent:
        try:
            host = normalize_domain(domain)
        except ValueError as exc:
            raise ToolRequestError(f"domínio inválido: {exc}") from None
        if host.endswith(SIMULATED_TLD):
            return self._fixture(host)

        key = cache_key(TOOL, {"domain": host})
        hit = await self._cache.get(key)
        if hit is not None:
            return SiteContent.model_validate(hit | {"cached": True})

        pages: list[SitePage] = []
        errors: list[str] = []
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            transport=self._transport,
        ) as client:
            home = await self._first_ok(client, [f"https://{host}/", f"https://www.{host}/"])
            if isinstance(home, str):
                errors.append(f"home: {home}")
            else:
                home_url, home_html = home
                pages.append(_page("home", home_url, home_html))
                about_url = _find_about_link(home_html, home_url, host)
                if about_url:
                    try:
                        final_url, about_html = await self._get(client, about_url)
                        pages.append(_page("about", final_url, about_html))
                    except _FetchError as exc:
                        errors.append(f"about: {exc}")

        content = SiteContent(
            domain=host, pages=pages, errors=errors, retrieved_at=datetime.now(UTC)
        )
        if pages:  # falha de rede é transitória: só o sucesso vai para o cache
            await self._cache.set(
                key, TOOL, {"domain": host}, content.model_dump(mode="json", exclude={"cached"})
            )
        return content

    async def _first_ok(self, client: httpx.AsyncClient, urls: list[str]) -> tuple[str, str] | str:
        last_error = ""
        for url in urls:
            try:
                return await self._get(client, url)
            except _FetchError as exc:
                last_error = str(exc)
        return last_error

    async def _get(self, client: httpx.AsyncClient, url: str) -> tuple[str, str]:
        """GET com redirects manuais, checando SSRF em cada salto. Devolve (url final, html)."""
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_public(url)
            try:
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        url = urljoin(url, location)
                        continue
                    if response.status_code != httpx.codes.OK:
                        raise _FetchError(f"HTTP {response.status_code}")
                    ctype = response.headers.get("content-type", "")
                    if "html" not in ctype.lower():
                        raise _FetchError(f"conteúdo não é HTML ({ctype[:40] or 'sem tipo'})")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_HTML_BYTES:
                            raise _FetchError("página grande demais")
                    return url, body.decode(response.encoding or "utf-8", errors="replace")
            except httpx.TimeoutException:
                raise _FetchError("timeout") from None
            except httpx.TransportError as exc:
                raise _FetchError(f"erro de rede ({type(exc).__name__})") from None
        raise _FetchError("redirects demais")

    async def _check_public(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"}:
            raise _FetchError(f"esquema não permitido ({parts.scheme})")
        if parts.username or parts.password:
            raise _FetchError("URL com credenciais")
        try:
            port = parts.port
        except ValueError:
            raise _FetchError("porta inválida") from None
        if port not in {None, 80, 443}:
            raise _FetchError(f"porta não permitida ({port})")
        host = parts.hostname or ""
        try:
            addresses = [host] if _is_ip(host) else await self._resolver(host)
        except OSError:
            raise _FetchError("DNS não resolveu") from None
        if not addresses:
            raise _FetchError("DNS não resolveu")
        for address in addresses:
            if not ipaddress.ip_address(address).is_global:
                raise _FetchError("destino não público bloqueado (SSRF)")

    def _fixture(self, host: str) -> SiteContent:
        now = datetime.now(UTC)
        path = (self._fixtures_dir / f"{host}.md") if self._fixtures_dir else None
        if path is None or not path.is_file():
            return SiteContent(
                domain=host, pages=[], errors=["domínio fictício sem fixture"],
                simulated=True, retrieved_at=now,
            )  # fmt: skip
        text = sanitize_text(path.read_text(encoding="utf-8"))[:MAX_PAGE_CHARS]
        page = SitePage(kind="about", url=HttpUrl(f"https://{host}/"), text=text)
        return SiteContent(domain=host, pages=[page], simulated=True, retrieved_at=now)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _page(kind: Literal["home", "about"], url: str, html: str) -> SitePage:
    text = trafilatura.extract(html, url=url, include_comments=False, favor_recall=True) or ""
    return SitePage(kind=kind, url=HttpUrl(url), text=sanitize_text(text)[:MAX_PAGE_CHARS])


def _find_about_link(html: str, base_url: str, host: str) -> str | None:
    """Primeiro link para a página institucional no mesmo site (host ou subdomínio)."""
    try:
        doc = lxml_html.fromstring(html)
    except (ValueError, etree.ParserError):
        return None
    site_host = urlsplit(base_url).hostname or host
    allowed = {host, site_host, site_host.removeprefix("www.")}
    for anchor in doc.iterfind(".//a[@href]"):
        href = str(anchor.get("href") or "")
        label = anchor.text_content() or ""
        if not (_ABOUT.search(href) or _ABOUT.search(label)):
            continue
        url = urljoin(base_url, href)
        target = urlsplit(url).hostname or ""
        if urlsplit(url).scheme in {"http", "https"} and (
            target in allowed or any(target.endswith(f".{h}") for h in allowed)
        ):
            return url.split("#", 1)[0]
    return None
