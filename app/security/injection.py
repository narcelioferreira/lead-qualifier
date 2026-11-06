"""Detector determinístico de prompt injection (OWASP ASI01 / AST05), sem LLM.

Primeira camada de defesa: regras de alta precisão para padrões conhecidos, aplicadas à
mensagem, ao cargo e às evidências dos sites. A flag `injection` resultante é **somada** à do
LLM (basta uma das duas para a regra K1 desqualificar o lead). Não substitui o guardrail com
SLM (T28): regra pega o óbvio e barato; o modelo pega a variação.

Os padrões vêm de conhecimento geral (OWASP LLM01), dos ataques do split **dev** e do conjunto
sintético do guardrail (`evals/guardrail_set.jsonl`): ajustar regras olhando o split test
contaminaria a avaliação.

A normalização existe só para casar os padrões: o texto que segue para o modelo não muda, então
empresa com nome em cirílico ou grego continua intacta.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.schemas import sanitize_text

# (família, regex) sobre texto normalizado: minúsculo, sem acento, espaços colapsados.
_PATTERNS: tuple[tuple[str, str], ...] = (
    # Sobrescrever instruções: "ignore todas as instruções anteriores", "disregard previous".
    # "Regras" sozinho não conta: "não podemos ignorar as regras da Lei 13.103" é dor legítima.
    (
        "override",
        # Sem `\b` à esquerda: "caminhõesignore" esconde o verbo colado em outra palavra.
        r"((?<!\bs)ignor\w*|desconsider\w*|esquec\w*|disregard|forget)\b.{0,40}"
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
    # Diálogo forjado com o assistente (G014): dois turnos, ou o "assistente" confirmando o tier.
    (
        "fake_system",
        r"\b(cliente|usuario|user|human\w*)\s*:.{0,300}\b(assistente|assistant)\s*:",
    ),
    ("fake_system", r"\b(assistente|assistant)\s*:.{0,80}\btier [abcd]\b"),
    # Manipular a nota (específico do domínio): "classifique como tier A", "score 100".
    (
        "scoring",
        r"\b(classifi\w*|atribu\w*|marque|defina|set|rate|give)\b.{0,40}"
        r"\b(tier|nota|score|pontua\w*)\b.{0,15}\b([abcd]|100|maxim\w*|maximum)\b",
    ),
    ("scoring", r"\b(score|nota)\s*=\s*\d+"),
    # A avaliação escrita como JSON embutido (G011): chave entre aspas, `"tier": "A"`.
    ("scoring", r"[\"'“”‘’](tier|score|nota|override|avaliacao\w*)[\"'“”‘’]\s*:"),
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
# Parecem espaço vazio, mas não são Cc/Cf nem Mn: U+3164 e U+FFA0 viram U+1160 no NFKC.
_BLANK_LOOKALIKES = "\u115f\u1160\u2800\u3164\uffa0"
_DROP_BLANKS = str.maketrans(dict.fromkeys(_BLANK_LOOKALIKES))
_BLANKS_AS_SPACE = str.maketrans(dict.fromkeys(_BLANK_LOOKALIKES, " "))
# Só minúsculas (roda depois do `lower`). Cirílico, grego e latim estendido que imitam o latim.
_HOMOGLYPHS = str.maketrans(
    {
        **dict(zip("авеікмнорстухѕјһԁԛԝ", "abeikmhopctyxsjhdqw", strict=True)),
        **dict(zip("αβγεικνορτυχω", "abyeikvoptuxw", strict=True)),
        **dict(zip("ıɑɡօ", "iago", strict=True)),
    }
)


@dataclass(frozen=True)
class InjectionHit:
    source: str  # "lead" ou id da evidência (E1, E2...)
    family: str


def normalize(text: str, *, blanks: dict[int, Any] = _DROP_BLANKS) -> str:
    # sanitize_text remove zero-width e bidi (Cc/Cf): dupla defesa para o texto dos sites.
    visible = sanitize_text(text).translate(blanks)
    decomposed = unicodedata.normalize("NFKD", visible)
    # Mn cobre os acentos e também os seletores de variação (combining class 0).
    no_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return _SPACES.sub(" ", no_marks.lower().translate(_HOMOGLYPHS)).strip()


def scan(text: str) -> set[str]:
    """Famílias de padrões de injeção encontradas no texto."""
    # O caractere em branco pode estar no meio da palavra ("ig_nore") ou no lugar do espaço.
    variants = {normalize(text), normalize(text, blanks=_BLANKS_AS_SPACE)}
    return {family for family, rx in _COMPILED for clean in variants if rx.search(clean)}


def scan_sources(sources: Iterable[tuple[str, str]]) -> list[InjectionHit]:
    """`sources` = pares (origem, texto). Devolve um hit por origem e família."""
    return [
        InjectionHit(source, family) for source, text in sources for family in sorted(scan(text))
    ]
