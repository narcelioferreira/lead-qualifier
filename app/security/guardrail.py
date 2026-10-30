"""Veredito do guardrail de entrada (T28), validado por schema (structured output).

Fica fora de `app/graph` para o state do grafo poder tipar o campo sem import circular.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.ontology.models import LeadFlag

REASON_CHARS = 300


class GuardrailVerdict(BaseModel):
    """Resposta do guardrail. Booleans e uma frase: nada que o grafo execute ou copie para o CRM."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # A justificativa vem primeiro: o modelo decide depois de "explicar".
    reason: str = Field(max_length=REASON_CHARS)
    is_injection: bool
    is_spam: bool
    is_out_of_scope: bool

    @property
    def blocks(self) -> bool:
        return self.is_injection or self.is_spam

    @property
    def flags(self) -> frozenset[LeadFlag]:
        """Flags da ontologia que levam à K1. Fora de escopo não vira flag (ver o nó)."""
        found: set[LeadFlag] = set()
        if self.is_injection:
            found.add(LeadFlag.INJECTION)
        if self.is_spam:
            found.add(LeadFlag.SPAM)
        return frozenset(found)
