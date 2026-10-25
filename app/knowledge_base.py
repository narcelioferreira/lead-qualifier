"""Base de conhecimento interna da FrotaSense (T23), usada pelo RAG agêntico (Fase F).

Cada documento é um Markdown em `knowledge_base/` com front-matter YAML (lido com
`yaml.safe_load`) validado por `KBMetadata`. O carregamento falha cedo se algo estiver
errado, e não silenciosamente na ingestão (T24) ou no prompt (T26).

O texto da base vai para o prompt do `suggest_next_step` como **contexto confiável**, então
um documento envenenado seria uma injeção com a autoridade da empresa (OWASP ASI06). Por isso
o corpo de cada documento passa por quatro verificações:
- o detector determinístico de injeção (`app.security.injection`);
- sem caracteres invisíveis ou de controle (os mesmos que o `sanitize_text` remove);
- sem HTML nem links: o próximo passo cita o `doc_id`, nunca uma URL;
- sem dados pessoais (e-mail, telefone, CPF ou CNPJ): a base é fictícia e vai para o LLM.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.ontology.loader import load_sector_taxonomy
from app.ontology.models import SectorFit
from app.schemas import Tier
from app.security.injection import scan

KB_DIR = Path(__file__).parent.parent / "knowledge_base"
# Arquivos da pasta que não são documentos da base.
IGNORED_FILES = frozenset({"README.md"})
MAX_DOC_BYTES = 20_000

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## \S", re.MULTILINE)
_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("html", re.compile(r"<\s*/?\s*[a-zA-Z!]")),
    ("link", re.compile(r"https?://|\bwww\.|\]\(", re.IGNORECASE)),
    ("e-mail", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("telefone", re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")),
    ("CPF", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("CNPJ", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
)


class KBError(ValueError):
    """Documento da base de conhecimento inválido."""


class DocType(StrEnum):
    PLAYBOOK = "playbook"  # o que fazer com um lead de cada tier
    CASE = "case"  # resultado de um cliente fictício de um segmento
    OBJECTION = "objection"  # objeção comum e como responder
    PRODUCT = "product"  # módulos, preços, implantação e integrações


class Segment(StrEnum):
    """Segmentos de mercado da FrotaSense. O `SectorFit` vem do CNAE, pela taxonomia."""

    TRANSPORTE_CARGAS = "transporte_cargas"
    DISTRIBUICAO = "distribuicao"
    LOGISTICA = "logistica"
    AGRONEGOCIO = "agronegocio"
    CONSTRUCAO = "construcao"
    SERVICOS_CAMPO = "servicos_campo"
    LOCADORA = "locadora"


# CNAE representativo de cada segmento: o setor do documento sai da mesma taxonomia que
# classifica o lead, e não de um rótulo escrito à mão que poderia divergir dela.
SEGMENT_CNAE: dict[Segment, str] = {
    Segment.TRANSPORTE_CARGAS: "4930-2",
    Segment.DISTRIBUICAO: "46",
    Segment.LOGISTICA: "5211-7",
    Segment.AGRONEGOCIO: "01",
    Segment.CONSTRUCAO: "42",
    Segment.SERVICOS_CAMPO: "36",
    Segment.LOCADORA: "7711-0",
}

DocId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]


class KBMetadata(BaseModel):
    """Front-matter de um documento. Listas vazias significam "vale para todos"."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    doc_id: DocId
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    doc_type: DocType
    tiers: tuple[Tier, ...] = ()
    segments: tuple[Segment, ...] = ()
    version: int = Field(ge=1)
    updated: date

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.tiers)) != len(self.tiers):
            raise ValueError("tier repetido")
        if len(set(self.segments)) != len(self.segments):
            raise ValueError("segmento repetido")
        if self.doc_type is DocType.PLAYBOOK and len(self.tiers) != 1:
            raise ValueError("playbook precisa de exatamente um tier")
        if self.doc_type is DocType.CASE:
            if len(self.segments) != 1:
                raise ValueError("case precisa de exatamente um segmento")
            if not self.tiers or Tier.D in self.tiers:
                raise ValueError("case precisa de tier e não se aplica ao tier D")
        return self

    @property
    def sectors(self) -> frozenset[SectorFit]:
        """`SectorFit` dos segmentos (filtro do RAG pelo setor da ontologia)."""
        taxonomy = load_sector_taxonomy()
        return frozenset(taxonomy.classify(SEGMENT_CNAE[s]) for s in self.segments)


@dataclass(frozen=True)
class KBDocument:
    metadata: KBMetadata
    body: str
    path: Path


def content_issues(text: str) -> list[str]:
    """Problemas de segurança no texto de um documento (vazio se estiver limpo)."""
    issues = [f"injeção ({family})" for family in sorted(scan(text))]
    if any(ch not in "\n\t" and unicodedata.category(ch) in {"Cc", "Cf"} for ch in text):
        issues.append("caractere invisível ou de controle")
    issues += [name for name, rx in _FORBIDDEN if rx.search(text)]
    return issues


def parse_document(text: str, path: Path) -> KBDocument:
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise KBError(f"{path.name}: front-matter ausente ou mal delimitado")
    raw_meta, body = match.groups()
    try:
        data = yaml.safe_load(raw_meta)
    except yaml.YAMLError as exc:
        raise KBError(f"{path.name}: front-matter não é YAML válido") from exc
    if not isinstance(data, dict):
        raise KBError(f"{path.name}: front-matter precisa ser um mapeamento")
    try:
        metadata = KBMetadata.model_validate(data)
    except ValueError as exc:
        raise KBError(f"{path.name}: metadados inválidos: {exc}") from exc
    if metadata.doc_id != path.stem:
        raise KBError(f"{path.name}: doc_id {metadata.doc_id!r} difere do nome do arquivo")
    body = body.strip()
    if not _SECTION.search(body):
        raise KBError(f"{path.name}: sem seções '## ' (o chunking é por seção)")
    issues = content_issues(raw_meta + "\n" + body)
    if issues:
        raise KBError(f"{path.name}: conteúdo recusado: {', '.join(issues)}")
    return KBDocument(metadata=metadata, body=body, path=path)


def load_knowledge_base(directory: Path = KB_DIR) -> tuple[KBDocument, ...]:
    """Carrega e valida todos os documentos da base, em ordem de `doc_id`."""
    docs: list[KBDocument] = []
    for path in sorted(directory.glob("*.md")):
        if path.name in IGNORED_FILES:
            continue
        if path.is_symlink() or not path.is_file():
            raise KBError(f"{path.name}: só arquivos regulares (sem links simbólicos)")
        if path.stat().st_size > MAX_DOC_BYTES:
            raise KBError(f"{path.name}: maior que {MAX_DOC_BYTES} bytes")
        docs.append(parse_document(path.read_text(encoding="utf-8"), path))
    if not docs:
        raise KBError(f"nenhum documento em {directory}")
    return tuple(docs)
