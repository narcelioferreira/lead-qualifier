"""Política de roteamento (T29): regras determinísticas, testáveis e auditáveis, sem LLM-router.

Cada etapa do grafo tem uma rota: o modelo principal e, em ordem, os de reserva. A política
decide três coisas e nunca chama modelo nenhum:

- **principal:** o primeiro modelo da rota;
- **fallback:** o próximo da rota quando o anterior ficou indisponível depois dos retries do
  cliente (429, 5xx, timeout ou rede). No guardrail, também quando a saída veio fora do schema
  duas vezes (ADR 0006);
- **escalonamento:** na extração dos critérios (`normalize`), o modelo maior refaz a extração
  quando a confiança do perfil é baixa ou o score cai na fronteira de um tier.

O escalonamento é na extração, e não na justificativa (`assess`): é o `normalize` que decide o
nível de cada critério; a justificativa não muda o score. O plano (`docs/04-plano-de-tasks.md`)
chamava as duas etapas juntas de `assess_criteria`.

Cada decisão vira um passo da auditoria (`route_reason` começando por `roteamento:`), e o
`audit_log` grava a lista completa em `routing_decisions` (`decisions_from_steps`).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.llm.base import LLMError, LLMOutputError, LLMUnavailableError
from app.ontology.scoring import ScoreResult

MINI = "groq-mini"
LARGE = "groq-large"
SLM = "ollama-slm"
# Confiança determinística (`extraction.confidence`) abaixo disto escala (doc 00, seção 4).
CONFIDENCE_MIN = 0.7
ROUTING_PREFIX = "roteamento:"
# Folga do orçamento da execução com a política: 1 extração no modelo maior (com 1 nova
# tentativa), que pensa mais (reasoning_effort medium) e gasta mais tokens de saída.
ROUTING_CALLS = 2
ROUTING_TOKENS = 16_000


class Trigger(StrEnum):
    UNAVAILABLE = "unavailable"
    INVALID_OUTPUT = "invalid_output"
    LOW_CONFIDENCE = "low_confidence"
    BORDERLINE = "borderline"


@dataclass(frozen=True)
class Route:
    """Modelos de uma etapa, em ordem: o primeiro é o principal; os seguintes, as reservas."""

    models: tuple[str, ...]
    escalate_to: str | None = None
    fallback_on_invalid_output: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    stage: str
    model_key: str
    trigger: Trigger
    detail: str

    @property
    def reason(self) -> str:
        """Texto gravado no `route_reason` do passo (sem nada vindo do lead)."""
        return f"{ROUTING_PREFIX} {self.trigger.value} → {self.model_key} ({self.detail})"


DEFAULT_ROUTES: Mapping[str, Route] = {
    "guardrail": Route((MINI, SLM), fallback_on_invalid_output=True),
    "agentic_research": Route((MINI, LARGE)),
    "normalize": Route((MINI, LARGE), escalate_to=LARGE),
    "assess": Route((MINI, LARGE)),
    "suggest_next_step": Route((MINI, LARGE)),
}


@dataclass(frozen=True)
class RoutingPolicy:
    routes: Mapping[str, Route] = field(default_factory=lambda: dict(DEFAULT_ROUTES))
    confidence_min: float = CONFIDENCE_MIN
    # Rota de etapa sem rota própria: só o mini, sem reserva.
    default: Route = Route((MINI,))

    def route(self, stage: str) -> Route:
        return self.routes.get(stage, self.default)

    def primary(self, stage: str) -> str:
        return self.route(stage).models[0]

    def fallback(self, stage: str, failed: str, error: LLMError) -> RoutingDecision | None:
        """Próximo modelo da rota depois de `failed`, ou `None` se o erro não justifica trocar.

        Requisição rejeitada (4xx que não seja 429) não troca de modelo: o problema é o pedido.
        """
        route = self.route(stage)
        if isinstance(error, LLMUnavailableError):
            trigger = Trigger.UNAVAILABLE
        elif isinstance(error, LLMOutputError) and route.fallback_on_invalid_output:
            trigger = Trigger.INVALID_OUTPUT
        else:
            return None
        if failed not in route.models:
            return None
        rest = route.models[route.models.index(failed) + 1 :]
        if not rest:
            return None
        return RoutingDecision(stage, rest[0], trigger, f"{failed} falhou")

    def escalation(
        self, stage: str, current: str, confidence: float, score: ScoreResult
    ) -> RoutingDecision | None:
        """Modelo maior quando a extração ficou incerta ou o lead está na fronteira de um tier."""
        target = self.route(stage).escalate_to
        if target is None or current == target:
            return None
        if confidence < self.confidence_min:
            detail = f"confiança {confidence:.2f} < {self.confidence_min:.2f}"
            return RoutingDecision(stage, target, Trigger.LOW_CONFIDENCE, detail)
        if score.is_borderline:
            detail = f"score {score.score:g} na fronteira do tier {score.tier.value}"
            return RoutingDecision(stage, target, Trigger.BORDERLINE, detail)
        return None


# Referência de custo da T30 (ablação 5): toda etapa no modelo maior, sem reserva nem
# escalonamento. O guardrail também, para a única diferença em relação à `routing` ser o modelo.
LARGE_ONLY = RoutingPolicy(routes={}, default=Route((LARGE,)))


def decisions_from_steps(steps: Sequence[Any]) -> list[dict[str, Any]]:
    """Rota de cada chamada de modelo e cada decisão da política, na ordem em que ocorreram.

    `steps` são `StepRecord` (tipados como `Any` para a política não depender da auditoria).
    """
    decisions = []
    for step in steps:
        reason = step.route_reason or ""
        if step.model_key or reason.startswith(ROUTING_PREFIX):
            decisions.append(
                {"node": step.node, "model_key": step.model_key, "route_reason": step.route_reason}
            )
    return decisions
