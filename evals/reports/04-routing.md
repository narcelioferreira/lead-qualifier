# Avaliação: routing × large_only (T30)

- **Configurações:** `routing` e `large_only`, as duas com prompts `v6`
- **Splits:** dev (20 leads) e test (30 leads, rodada **única** com `--confirm-test`, em partes por causa da cota)
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência
- **Gerado em:** 2026-11-05 (test concluído às 19h06 UTC)

## Resultado

**No test, a `routing` custou 35% da `large_only` e não perdeu acurácia: 70,0% contra 66,7%.** A diferença entre as duas está dentro do ruído (McNemar p = 1,0): elas deram o mesmo tier em 27 dos 30 leads. O que a medição sustenta é "mesma qualidade por um terço do custo", e não "a `routing` é melhor".

Nenhuma comparação entre configurações vizinhas chegou a p < 0,05 no test. Com 30 leads, cada lead vale 3,3 pontos percentuais.

![Custo × acurácia por configuração](04-routing-custo-acuracia.svg)

| Configuração | Split | Acurácia (IC 95%) | κ ponderado | Custo por lead | Tokens por lead | Latência p50 |
|---|---|---:|---:|---:|---:|---:|
| `baseline` | dev (20) | 70,0% (50,0%–90,0%) | 0,655 | US$ 0,000169 | 1.786 | 0,8 s |
| `baseline` | test (30) | 53,3% (33,3%–70,0%) | 0,475 | US$ 0,000147 | 1.618 | 0,8 s |
| `mvp` | dev (20) | 95,0% (85,0%–100,0%) | 0,961 | US$ 0,000358 | 3.698 | 2,7 s |
| `mvp` | test (30) | 60,0% (43,3%–76,7%) | 0,560 | US$ 0,000356 | 3.698 | 4,6 s |
| `rag` | dev (20) | 90,0% (75,0%–100,0%) | 0,884 | US$ 0,000722 | 7.670 | 8,3 s |
| `rag` | test (30) | 66,7% (50,0%–83,3%) | 0,662 | US$ 0,000759 | 8.013 | 11,9 s |
| `routing` | dev (20) | 80,0% (60,0%–95,0%) | 0,813 | US$ 0,000934 | 8.766 | 31,9 s |
| `routing` | test (30) | 70,0% (53,3%–86,7%) | 0,733 | US$ 0,000968 | 9.230 | 41,4 s |
| `large_only` | dev (20) | 75,0% (55,0%–95,0%) | 0,772 | US$ 0,002770 | 10.771 | 54,5 s |
| `large_only` | test (30) | 66,7% (50,0%–83,3%) | 0,681 | US$ 0,002762 | 10.609 | 64,2 s |

O custo é **equivalente**, calculado pelo preço de lista: as rodadas usaram o plano gratuito da Groq.

## O que está sendo medido

| | `routing` | `large_only` |
|---|---|---|
| Grafo | pesquisa agêntica, próximo passo com RAG e guardrail | o mesmo |
| Modelos | `RoutingPolicy()`: mini por padrão, com escalonamento da extração | tudo no `groq-large`, sem reserva nem escalonamento |
| Prompts | `v6` | `v6` |

A única diferença entre as duas é o modelo. Em relação à `rag` (`v5`), a `routing` acrescenta o guardrail e a política, e os prompts da `v6` são outros.

**Estes números não valem para a API.** Desde a T33 (parte 3), a API usa o grafo do MVP com os prompts `v6` e o guardrail, sem pesquisa agêntica, próximo passo nem política. Essa combinação não foi avaliada.

## Comparações no test

Mesmos leads, com diferença pareada e McNemar exato (`evals/compare.py`).

| Comparação | Diferença de acurácia (IC 95%) | Só a 1ª acertou / só a 2ª acertou | McNemar p |
|---|---:|---:|---:|
| `routing` − `large_only` | +3,3 p.p. (−6,7 a +13,3) | 2 / 1 | 1,000 |
| `routing` − `rag` | +3,3 p.p. (−10,0 a +16,7) | 3 / 2 | 1,000 |
| `routing` − `mvp` | +10,0 p.p. (−3,3 a +26,7) | 4 / 1 | 0,375 |

Relatórios: `large_only-v6-vs-routing-test.md`, `routing-v6-vs-rag-test.md`, `routing-v6-vs-mvp-test.md`, `routing-test.md` e `large_only-test.md`. Os do dev estão em `dev/`.

## Roteamento

- **Divisão de tokens:** 92,9% no mini (257.226) e 7,1% no modelo maior (19.677).
- **Escalonamento:** 5 de 30 leads, 4 por score na fronteira e 1 por confiança baixa (0,27). Nos 5, a `routing` deu o mesmo tier da `large_only`: L004, L006, L016, L022 e L048. Três acertaram e dois erraram (L016 e L048), então escalar não garantiu acerto.
- **Fallback:** nenhum. O modelo maior só foi chamado nos 5 escalonamentos, e o guardrail respondeu sempre pelo principal. A troca silenciosa de modelo não contaminou esta rodada.
- **Dev:** a `routing` ficou em 80% e a `large_only` em 75% (McNemar p = 1,0). Só o L039 mudou por causa do roteamento: o modelo maior marcou o estagiário como `student` (K4 → D; gabarito C). L042, L045 e L035 mudaram por variância da pesquisa.

## Guardrail

| | `rag` | `routing` | `large_only` |
|---|---:|---:|---:|
| Ataques desqualificados (test) | 3/4 | 4/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 | 0/26 |

- 3 dos 4 ataques pararam na regra determinística, sem chamar modelo.
- O L034 (spam) escapava nas rodadas anteriores (`mvp` e `rag` deram C) e agora é barrado pelo modelo.
- Em média, cada checagem no mini custou 853 tokens e 0,8 s (27 checagens; os 3 barrados pela regra não chamam modelo).
- São 4 ataques: o resultado mostra o comportamento nesses casos, sem estimar uma taxa.

## Latência

A latência p50 de 41,4 s da `routing` não vem do guardrail. Ela se concentra no mini em `normalize` (14,6 s em média), `suggest_next_step` (11,9 s) e `assess` (9,8 s), enquanto o `normalize` no modelo maior levou 2,6 s em média. **A causa não foi investigada.** Como as rodadas usaram o plano gratuito, esses números não servem como estimativa de produção.

## Erros no test (achados, sem ajuste)

Os erros do test ficam registrados e não viram ajuste de prompt. A `routing` errou 9 leads e a `large_only`, 10. Oito erros são comuns às duas:

| Padrão | Leads | Gabarito → previsto |
|---|---|---|
| B promovido a A | L003, L009, L014, L023 | B → A |
| C promovido a B | L016, L048 | C → B |
| A rebaixado a B | L044 | A → B |
| Homônimo: fonte de outro domínio | L013 | D → B |

Só uma das configurações errou:

| Lead | Gabarito | `routing` | `large_only` | Observação |
|---|---|---|---|---|
| L010 | B | A | B | mesmo padrão B → A |
| L025 | C | C | D | K2 só na `large_only` |
| L049 | B | B | D | K6 só na `large_only` |

O padrão B → A vem desde a T16 e é o erro mais frequente: na `routing`, 5 dos 9 leads B saíram A. Como também acontece no modelo maior, um modelo mais caro não é a resposta evidente: a causa deve ser investigada na extração e na rubrica, com casos do dev.

## Ressalvas da execução

- **Rodadas em partes:** a cota de 200K tokens por dia exigiu dividir o test em 4/11 e 5/11. O digest de integridade foi o mesmo (`3bb59143…`). Os commits feitos entre as partes não mudam o caminho da avaliação: a rodada não usa CRM, checkpointer nem API.
- **L039 refeito no dev:** na primeira vez, o escalonamento levou 429 de tokens por minuto porque a `large_only` rodava em paralelo. As duas dividem os 8K tokens por minuto do modelo maior e, depois disso, não rodaram mais ao mesmo tempo.
- **L003 no test:** o site deu timeout nas duas configurações (`site: home: timeout`). A execução continuou com a busca, e o lead saiu A contra o gabarito B. Esse caso também tem o achado de porte contraditório da T27.
- **Gabarito:** anotador único.

## Reprodução

```bash
uv run python -m evals.run --split test --config routing --prompt-version v6 --confirm-test --resume evals/runs/routing-v6-test.jsonl --report evals/reports/routing-test.md
uv run python -m evals.run --split test --config large_only --prompt-version v6 --confirm-test --resume evals/runs/large_only-v6-test.jsonl --report evals/reports/large_only-test.md
uv run python -m evals.compare evals/runs/routing-v6-test.jsonl evals/runs/large_only-v6-test.jsonl --out evals/reports/large_only-v6-vs-routing-test.md --title "large_only × routing (test)" --names routing large_only
uv run python -m evals.cost_chart
```
