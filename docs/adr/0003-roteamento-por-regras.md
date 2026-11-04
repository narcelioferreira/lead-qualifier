# ADR 0003: roteamento de modelos por regras

- **Status:** aceito (2026-10-30, T29)
- **Evidência:** `app/routing/policy.py`, `tests/unit/test_routing.py`,
  `evals/reports/dev/routing-v6.md`. A comparação final de custo fica em `04-routing.md` (T30, em
  andamento)

## Contexto

O agente usa um modelo pequeno (`groq-mini`) e um maior (`groq-large`). O maior custa mais e tem o
mesmo limite de 8K tokens por minuto do plano gratuito. Sempre usar o maior desperdiçaria dinheiro
e cota em leads fáceis, e sempre usar o menor deixaria sem ajuda os leads difíceis.

## Decisão

Uma **política determinística**, sem LLM-router e sem I/O (`RoutingPolicy`):

1. **Rota por etapa:** guardrail `mini → qwen3:4b` ([ADR 0006](0006-guardrail.md)); pesquisa,
   extração, justificativa e próximo passo `mini → groq-large`.
2. **Fallback** para o próximo modelo da rota só depois dos retries do cliente (429, 5xx, timeout
   ou rede). Outros 4xx não trocam de modelo, porque o problema é o pedido. Saída inválida só troca
   no guardrail.
3. **Escalonamento da extração** para o `groq-large` com confiança abaixo de 0,7 ou score a ±5
   pontos de um limite de tier. Ocorre uma vez por extração; se o maior falhar, fica a extração do
   mini.
4. **Cada decisão vai para a auditoria**, com etapa, modelo e motivo (`routing_decisions`).

**Desvio do plano:** o plano punha o escalonamento no `assess_criteria`. Quem decide o nível de cada
critério é o `normalize`, e o `assess` só escreve a justificativa. Escalar a justificativa não
mudaria nenhum tier.

## Consequências

- **Testável e explicável:** `policy.py` tem 100% de cobertura, e o motivo de cada troca é texto da
  própria política, sem nada do lead.
- **O modelo maior não garante acerto.** No dev (20 leads), a `routing` fez 80% / κ 0,813 contra
  90% do `rag`, com McNemar p 0,63, ou seja, dentro do ruído. Na auditoria desse dev, só o L039
  mudou pelo roteamento, e para pior: o maior marcou o estagiário como `student`, o que levou à K4 e
  ao tier D, com gabarito C.
- **Gasto sem efeito em alguns casos:** o escalonamento também ocorre em leads que vão a D por regra
  eliminatória (L027), onde o maior não tem como mudar o tier.
- **Troca silenciosa de modelo:** com a cota do mini esgotada, a política passa para o maior. Em
  produção isso dá disponibilidade; nas avaliações, contaminaria a medição, então cada rodada confere
  o orçamento antes e os modelos usados depois.
- **Limiares fixos:** os valores 0,7 e ±5 são escolhas de projeto, ainda não calibradas.

## Alternativas descartadas

- **LLM-router:** gastaria tokens em toda chamada para decidir, e a decisão ficaria não
  determinística e sujeita a injeção. Não foi implementado nem medido.
- **Só o modelo maior:** é a configuração `large_only`, mantida como referência de custo.
