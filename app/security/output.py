"""Saneamento da saída do LLM antes de ela sair do agente (OWASP ASI09 / LLM05).

A justificativa vai para a Note do HubSpot (Fase E), lida por vendedores que confiam no agente.
Se ela carregar HTML, links ou texto copiado de um site malicioso, o agente vira um
retransmissor da injeção. Regras:
- remove tags HTML/Markdown de imagem e link, mantendo só o texto visível;
- só mantém URLs que estão nas evidências coletadas; as demais viram "[link removido]";
- host sem esquema (`evil.com/x`) segue a mesma regra, para não virar link clicável no CRM;
- remove e-mail e telefone: dado pessoal copiado de um site não vai para a Note;
- remove caracteres de controle e invisíveis, e limita o tamanho.

`echoes_prompt` confere à parte se a saída repete o system prompt (ASI01). Quem chama descarta o
texto inteiro, porque recortar o trecho deixaria o resto da resposta de um modelo enganado.
"""

import re
from collections.abc import Iterable

from app.schemas import sanitize_text
from app.security.injection import normalize

MAX_RATIONALE_CHARS = 2000
REMOVED_LINK = "[link removido]"
REMOVED_EMAIL = "[e-mail removido]"
REMOVED_PHONE = "[telefone removido]"
# Palavras seguidas iguais ao prompt para contar como cópia: curto o bastante para um trecho
# colado e longo o bastante para não pegar termos da rubrica ("gestor de frota da empresa").
ECHO_WORDS = 8

_TAG = re.compile(r"<[^>]{0,200}>")
_MD_IMAGE = re.compile(r"!\[([^\]]{0,200})\]\([^)]{0,500}\)")
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\(([^)]{0,500})\)")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_SCHEMES = re.compile(r"\b(?:javascript|data|vbscript|file):", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")
# Formatos de telefone, para não pegar CNAE (4930-2/02), datas, anos nem valores.
_PHONE = re.compile(
    r"\+\d[\d\s().-]{7,18}\d"  # internacional: +55 11 91234-5678
    r"|(?<![\w/.-])\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b(?![/-]\d)"  # (11) 91234-5678
    r"|\b9\d{4}-\d{4}\b"  # celular sem DDD
)
_BARE_HOST = re.compile(
    r"\b(?P<host>(?:[a-z0-9][a-z0-9-]{0,62}\.){1,8}(?P<tld>[a-z]{2,24}))\b"
    r"(?P<path>/[^\s<>\"')\]]{0,500})?",
    re.IGNORECASE,
)
# Fora destes, só conta como host se estiver todo em minúsculas: "Frota.Segundo", com o espaço
# esquecido depois do ponto, é texto; "EVIL.COM" não é.
_COMMON_TLDS = frozenset(
    {"com", "net", "org", "br", "io", "co", "info", "biz", "xyz", "app", "dev", "ai", "me"}
    | {"ru", "cn", "top", "site", "online", "link", "click", "zip"}
)
_WORD = re.compile(r"\w+")


def _canonical(url: str) -> str:
    return url.lower().rstrip("/.,;:").removeprefix("https://").removeprefix("http://")


def _host_of(canonical: str) -> str:
    return canonical.split("/", 1)[0].removeprefix("www.")


def _bare_host(match: re.Match[str], allowed: set[str], hosts: set[str]) -> str:
    token, host = match.group(0), match.group("host")
    if not host.islower() and match.group("tld").lower() not in _COMMON_TLDS:
        return token
    if match.group("path") and _canonical(match.group("path")).strip("/"):
        return token if _canonical(token) in allowed else REMOVED_LINK
    return token if _host_of(_canonical(host)) in hosts else REMOVED_LINK


def _words(text: str) -> list[str]:
    return _WORD.findall(normalize(text))


def echoes_prompt(text: str, prompts: Iterable[str]) -> bool:
    """A saída repete `ECHO_WORDS` palavras seguidas de algum prompt? Paráfrase passa."""
    said = _words(text)
    copied = {tuple(said[i : i + ECHO_WORDS]) for i in range(len(said) - ECHO_WORDS + 1)}
    for prompt in prompts:
        words = _words(prompt)
        if any(tuple(words[i : i + ECHO_WORDS]) in copied for i in range(len(words))):
            return True
    return False


def sanitize_rationale(text: str, allowed_urls: Iterable[str] = ()) -> str:
    allowed = {_canonical(u) for u in allowed_urls}
    hosts = {_host_of(u) for u in allowed}
    clean = sanitize_text(text)
    clean = _MD_IMAGE.sub(r"\1", clean)
    clean = _MD_LINK.sub(lambda m: f"{m.group(1)} {m.group(2)}", clean)
    clean = _TAG.sub("", clean)
    clean = _SCHEMES.sub("", clean)
    clean = _URL.sub(
        lambda m: m.group(0) if _canonical(m.group(0)) in allowed else REMOVED_LINK, clean
    )
    clean = _EMAIL.sub(REMOVED_EMAIL, clean)
    clean = _PHONE.sub(REMOVED_PHONE, clean)
    clean = _BARE_HOST.sub(lambda m: _bare_host(m, allowed, hosts), clean)
    return clean[:MAX_RATIONALE_CHARS].strip()
