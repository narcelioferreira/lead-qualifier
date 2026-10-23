"""HTTP comum aos clientes do HubSpot: base URL fixa, Bearer, retry e erros sem segredo.

Usado pelo setup das propriedades (T17) e pelo cliente de registros (T18). A base URL é fixa
(sem SSRF) e o token fica em `SecretStr`, fora de `repr` e das mensagens de erro.
"""

from typing import Any

import httpx
from pydantic import SecretStr
from tenacity.wait import wait_base

from app import retry
from tools_mcp.base import ToolRequestError, ToolUnavailableError

HUBSPOT_URL = "https://api.hubapi.com"
DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class HubSpotHttp:
    def __init__(
        self,
        token: SecretStr,
        *,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        retry_wait: wait_base | None = None,
        retry_sleep: retry.Sleep | None = None,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._retry_wait = retry_wait
        self._retry_sleep = retry_sleep

    def __repr__(self) -> str:
        return "HubSpotHttp()"

    def client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        return httpx.AsyncClient(base_url=HUBSPOT_URL, timeout=self._timeout, headers=headers)

    async def send(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        conflict_hint: str = "",
    ) -> dict[str, Any]:
        try:
            response, _ = await retry.send_with_retry(
                lambda: client.request(method, path, json=body),
                "hubspot",
                self._retry_wait,
                self._retry_sleep,
            )
        except retry.UpstreamUnavailableError as exc:
            raise ToolUnavailableError(str(exc)) from exc
        except retry.UpstreamRequestError as exc:
            if exc.status == 401:
                raise ToolRequestError(
                    "hubspot: token inválido ou expirado (HTTP 401); use uma chave de serviço"
                ) from exc
            if exc.status == 403:
                raise ToolRequestError(
                    f"hubspot: chave sem os escopos necessários (HTTP 403): {exc.detail}"
                ) from exc
            if exc.status == 409 and conflict_hint:
                raise ToolRequestError(f"hubspot: conflito em {path} ({conflict_hint})") from exc
            raise ToolRequestError(str(exc)) from exc
        data: Any = response.json() if response.content else {}
        return data if isinstance(data, dict) else {}
