"""Prompts versionados (`app/prompts/v{N}/*.md`) e delimitação de conteúdo não confiável.

Todo texto vindo do lead ou de sites entra no prompt dentro de um bloco com **nonce
aleatório** por chamada: um texto injetado não consegue "fechar" o bloco porque não conhece a
tag. O system prompt instrui a tratar o conteúdo do bloco sempre como dado.
"""

import secrets
from functools import cache
from pathlib import Path
from string import Template

from app.schemas import sanitize_text

PROMPTS_DIR = Path(__file__).parent
DEFAULT_VERSION = "v1"


@cache
def load_prompt(name: str, version: str = DEFAULT_VERSION) -> Template:
    if not name.isidentifier() or not version.startswith("v") or not version[1:].isdigit():
        raise ValueError(f"prompt inválido: {version}/{name}")
    return Template((PROMPTS_DIR / version / f"{name}.md").read_text(encoding="utf-8"))


def new_nonce() -> str:
    return secrets.token_hex(8)


def untrusted(text: str, nonce: str, origin: str) -> str:
    """Envolve texto não confiável num bloco `<dados_{nonce}>`. O texto sai sanitizado."""
    clean = sanitize_text(text).replace(nonce, "")
    return f'<dados_{nonce} origem="{origin}">\n{clean}\n</dados_{nonce}>'
