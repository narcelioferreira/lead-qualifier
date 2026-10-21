"""Detector determinístico de prompt injection (OWASP ASI01 / AST05), sem LLM.

Primeira camada de defesa: regras de alta precisão para padrões conhecidos, aplicadas à
mensagem, ao cargo e às evidências dos sites. A flag `injection` resultante é **somada** à do
LLM (basta uma das duas para a regra K1 desqualificar o lead). Não substitui o guardrail com
SLM (T28): regra pega o óbvio e barato; o modelo pega a variação.

Os padrões vêm de conhecimento geral (OWASP LLM01) e só dos ataques do split **dev**: ajustar
regras olhando o split test contaminaria a avaliação.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas import sanitize_text

# (família, regex) sobre texto normalizado: minúsculo, sem acento, espaços colapsados.
_PATTERNS: tuple[tuple[str, str], ...] = (
    # Sobrescrever instruções: "ignore todas as instruções anteriores", "disregard previous".
    # "Regras" sozinho não conta: "não podemos ignorar as regras da Lei 13.103" é dor legítima.
    (
        "override",
        r"\b(ignor\w*|desconsider\w*|esquec\w*|disregard|forget)\b.{0,40}"
        r"\b(instruc\w*|orientac\w*|anteriores|acima|previous|prior|above|instructions?)\b",
    ),
    # Trocar o papel do modelo: "você agora é", "you are now", "modo desenvolvedor".
    (
        "role",
        r"\b(voce agora e|agora voce e|you are now|act as|aja como|finja ser|pretend to be)\b",
    ),
    ("role", r"\b(developer mode|modo (de )?desenvolvedor|jailbreak|dan mode)\b"),
    # Falsa mensagem de sistema ou delimitador forjado.
    # "system:" em inglês é suspeito em qualquer posição; "sistema:" só no início ou após um
    # delimitador ("hoje usamos o sistema: planilhas" é legítimo).
    ("fake_system", r"\bsystem\s*:"),
    ("fake_system", r"(^|[\[<(>])\s*(sistema|assistant)\s*:"),
    ("fake_system", r"\[?\s*instruc\w* do sistema"),
    ("fake_system", r"</?\s*(lead|system|dados\w*|instructions?)\s*>"),
    # Manipular a nota (específico do domínio): "classifique como tier A", "score 100".
    (
        "scoring",
        r"\b(classifi\w*|atribu\w*|marque|defina|set|rate|give)\b.{0,40}"
        r"\b(tier|nota|score|pontua\w*)\b.{0,15}\b([abcd]|100|maxim\w*|maximum)\b",
    ),
    ("scoring", r"\b(score|nota)\s*=\s*\d+"),
    # Vazar o prompt ou dados: "print your system prompt", "exporte todos os contatos".
    ("leak", r"\b(system prompt|prompt do sistema|suas instrucoes|your instructions)\b"),
    (
        "leak",
        r"\b(export\w*|envi\w*|send|dump)\b.{0,30}\b(todos os|all)\b.{0,20}"
        r"\b(contatos|contacts|leads|dados|data|registros)\b",
    ),
    # Ocultar a manipulação: "não mencione esta instrução".
    ("conceal", r"\b(nao mencione|nao revele|do not mention|don't mention|nao conte)\b"),
)
_COMPILED = tuple((family, re.compile(rx)) for family, rx in _PATTERNS)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class InjectionHit:
    source: str  # "lead" ou id da evidência (E1, E2...)
    family: str


def normalize(text: str) -> str:
    # sanitize_text remove zero-width e bidi (Cc/Cf): dupla defesa para o texto dos sites.
    decomposed = unicodedata.normalize("NFKD", sanitize_text(text))
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", no_accents.lower()).strip()


def scan(text: str) -> set[str]:
    """Famílias de padrões de injeção encontradas no texto."""
    clean = normalize(text)
    return {family for family, rx in _COMPILED if rx.search(clean)}


def scan_sources(sources: Iterable[tuple[str, str]]) -> list[InjectionHit]:
    """`sources` = pares (origem, texto). Devolve um hit por origem e família."""
    return [
        InjectionHit(source, family) for source, text in sources for family in sorted(scan(text))
    ]
