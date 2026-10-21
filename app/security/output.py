"""Saneamento da saída do LLM antes de ela sair do agente (OWASP ASI09 / LLM05).

A justificativa vai para a Note do HubSpot (Fase E), lida por vendedores que confiam no agente.
Se ela carregar HTML, links ou texto copiado de um site malicioso, o agente vira um
retransmissor da injeção. Regras:
- remove tags HTML/Markdown de imagem e link, mantendo só o texto visível;
- só mantém URLs que estão nas evidências coletadas; as demais viram "[link removido]";
- remove caracteres de controle e invisíveis, e limita o tamanho.
"""

import re
from collections.abc import Iterable

from app.schemas import sanitize_text

MAX_RATIONALE_CHARS = 2000
REMOVED_LINK = "[link removido]"

_TAG = re.compile(r"<[^>]{0,200}>")
_MD_IMAGE = re.compile(r"!\[([^\]]{0,200})\]\([^)]{0,500}\)")
_MD_LINK = re.compile(r"\[([^\]]{0,200})\]\(([^)]{0,500})\)")
_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
_SCHEMES = re.compile(r"\b(?:javascript|data|vbscript|file):", re.IGNORECASE)


def _canonical(url: str) -> str:
    return url.lower().rstrip("/.,;:").removeprefix("https://").removeprefix("http://")


def sanitize_rationale(text: str, allowed_urls: Iterable[str] = ()) -> str:
    allowed = {_canonical(u) for u in allowed_urls}
    clean = sanitize_text(text)
    clean = _MD_IMAGE.sub(r"\1", clean)
    clean = _MD_LINK.sub(lambda m: f"{m.group(1)} {m.group(2)}", clean)
    clean = _TAG.sub("", clean)
    clean = _SCHEMES.sub("", clean)
    clean = _URL.sub(
        lambda m: m.group(0) if _canonical(m.group(0)) in allowed else REMOVED_LINK, clean
    )
    return clean[:MAX_RATIONALE_CHARS].strip()
