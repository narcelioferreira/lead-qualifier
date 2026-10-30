# Avaliação: rag × mvp (T27)

- **Configurações:** `mvp` (prompts `v2`) × `rag` (prompts `v5`, ajustados no dev a partir da `v4`)
- **Splits:** dev (20 leads, ajuste) e test (30 leads, rodada **única** com `--confirm-test`)
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência
- **Gerado em:** 2026-10-30 (test concluído às 17h03 UTC)

## O que está sendo medido

É a ablação (3) da arquitetura (`docs/00-arquitetura.md`, seção 11): o `mvp` mais o RAG agêntico.
A `rag` difere do `mvp` em dois nós e em nada mais:

| Nó | `mvp` | `rag` |
|---|---|---|
| Pesquisa | fixa: mensagem do lead, site declarado (home + sobre) e 1 busca pelo nome da empresa | `agentic_research` (T25): o mini aponta o que falta e propõe a consulta; o código valida e decide parar (até 3 iterações, teto de tokens) |
| normalize / assess | prompts `v2` | prompts da `v4`, **idênticos** byte a byte aos da `v2` |
| Score e tier | `scoring.py` + `rubric.yaml` | os mesmos |
| Próximo passo | — | `suggest_next_step` (T26): playbook e cases da base, com citação conferida pelo código |

Duas consequências para a leitura:

1. **O tier só muda pela pesquisa.** O próximo passo vem depois do score e não altera o tier.
   Qualquer diferença de acurácia ou kappa é efeito da evidência a mais (ou a menos) que o loop agêntico
   traz para a extração.
2. **O ganho do RAG no próximo passo não aparece na acurácia.** Ele é medido à parte, com o
   LLM-as-judge da T26 (seção "Próximo passo").

## Protocolo

1. Rodar a `rag` no dev (`python -m evals.run --split dev --config rag --prompt-version v4`) e
   comparar com a referência do MVP no dev (`evals/runs/mvp-v2-sec-dev.jsonl`, 95% / κ 0,961).
2. Ajustar só a partir de casos do dev. Um prompt novo vira `v5` e entra no
   `app/integrity.lock.json` (`scripts/lock_config.py`); a `v4` é imutável.
3. Rodar a configuração final **uma vez** no test e comparar com `evals/runs/mvp-v2-test.jsonl`.
   Os erros do test são registrados como achado e não viram ajuste.
4. Comparar nos **mesmos leads** com `evals/compare.py`: métricas lado a lado, diferença pareada de
   acurácia com IC 95% por bootstrap e teste exato de McNemar nos pares discordantes.

## Como ler os números

Com 20 leads no dev e 30 no test, cada lead vale 5 ou 3,3 pontos percentuais. A diferença pareada
só conta como efeito quando o McNemar sai abaixo de 5%. Para isso, os pares discordantes
precisam pender quase todos para um lado. Uma diferença dentro do ruído é registrada como tal,
e o aceite da T27 vale do mesmo jeito ("mesmo que o ganho seja pequeno, o resultado é registrado").

Há também a variância da própria Groq: na T16, L040 e L042 mudaram de tier entre duas rodadas do
`mvp` no dev **sem mudança de código**, mesmo com temperatura 0. Uma diferença de 1 ou 2 leads em
20 está dentro desse ruído, antes mesmo de qualquer teste estatístico.

No dev, a referência do MVP (95%) já está perto do teto. Ali, a `rag` serve para achar regressões
e o comportamento do loop (iterações, consultas repetidas, custo), e não para medir ganho.

## Dev (ajuste)

### Rodada 1: `rag` com `v4` (2026-10-27)

Comparação completa em `evals/reports/dev/rag-vs-mvp.md`; relatório da rodada em `evals/reports/dev/rag-v4.md`.

| | `mvp` (`v2`) | `rag` (`v4`) |
|---|---:|---:|
| Acurácia (IC 95%) | 95,0% (85,0%–100,0%) | 80,0% (60,0%–95,0%) |
| Kappa ponderado (IC 95%) | 0,961 (0,864–1,000) | 0,837 (0,660–0,959) |
| Tokens por lead | 3.698 | 7.761 (2,1×) |
| Latência p50 / p95 | 2,7 s / 16,6 s | 7,1 s / 19,7 s |
| Ataques → D / falso alarme K1 | 3/3 · 0/17 | 3/3 · 0/17 |

Diferença pareada: −15,0 p.p. (IC −35,0 a +5,0). Foram 4 leads que só o `mvp` acertou e 1 que só a
`rag` acertou; McNemar p = 0,375, dentro do ruído. Pesquisa: média de 2,0 iterações (6 leads com 1,
8 com 2 e 6 com 3). Próximo passo: 15 gerados com RAG e 5 no passo padrão (os tier D); 20 de 20 citam
um documento.

Os 5 leads que mudaram de tier foram conferidos na auditoria (`agent_steps`) e no cache das tools:

| Lead | Gabarito | `mvp` → `rag` | O que a pesquisa trouxe | Diagnóstico |
|---|---|---|---|---|
| L021 | A | B → A | 918 funcionários e sede em SP | ganho real |
| L035 | D | D → C | "548 funcionários, IT Services" (Sascar) | **regressão da extração:** com o snippet novo, o mini trocou `competitor` por `prospect`, embora a evidência diga "gestão de frotas e monitoramento de veículos e cargas", e a K2 se perdeu |
| L038 | A | A → B | "mais de 450 veículos" num post sobre **outra empresa** (Poggi Cargo) | **evidência atribuída à empresa errada** → 1000+ → teto C1 |
| L045 | A | A → B | 1.130 funcionários (LinkedIn) e 400 caminhões | a ontologia leva a 1000+ e ao teto C1; o gabarito diz "porte não informado" |
| L050 | B | B → C | "mais de 11 mil pessoas" | porte certo (C1); **setor errado**: "logística integrada de cargas fracionadas" virou `adjacent` |

### Ajustes feitos no dev: prompts `v5`

A `v5` é cópia da `v4` com mudanças **só no `normalize.md`**, escritas de forma genérica (sem citar
leads):

1. **Porte da própria empresa:** número de funcionários ou de veículos só vale quando o texto o
   atribui à empresa do lead; trecho sobre outra empresa (aquisição, parceira, cliente,
   controladora, nome parecido) vira `null`, mesmo que o título seja da empresa do lead (L038).
2. **Transportadora que se apresenta como "logística" continua `target`:** a classificação é pela
   atividade principal, como no CNAE (49.30 `target` × 52.11/52.50 `adjacent`) (L050).
3. **Concorrente pela atividade:** "monitoramento de veículos ou cargas" entra na definição, e porte,
   setor do LinkedIn ou tom da mensagem não mudam a classificação (L035).

**Custo para a ablação:** o normalize da `v5` deixa de ser idêntico ao da `v2`, então a diferença
`rag` × `mvp` no test mistura a pesquisa agêntica com essas três regras. Isso é registrado aqui e
na conclusão.

L045 e o porte do L050 não foram ajustados: o agente seguiu a ontologia, e o gabarito foi feito
sem o porte (ver Limitações).

### Rodada 2: `rag` com `v5` (2026-10-28)

Comparações completas em `evals/reports/dev/rag-v5-vs-mvp.md` e `evals/reports/dev/rag-v5-vs-v4.md`;
relatório da rodada em `evals/reports/dev/rag-v5.md`.

| | `mvp` (`v2`) | `rag` (`v4`) | `rag` (`v5`) |
|---|---:|---:|---:|
| Acurácia (IC 95%) | 95,0% (85,0%–100,0%) | 80,0% (60,0%–95,0%) | 90,0% (75,0%–100,0%) |
| Kappa ponderado (IC 95%) | 0,961 (0,864–1,000) | 0,837 (0,660–0,959) | 0,884 (0,686–1,000) |
| Tokens por lead | 3.698 | 7.761 | 7.670 (2,1×) |
| Latência p50 / p95 | 2,7 s / 16,6 s | 7,1 s / 19,7 s | 8,3 s / 18,8 s |
| Ataques → D / falso alarme K1 | 3/3 · 0/17 | 3/3 · 0/17 | 3/3 · 0/17 |

Diferenças pareadas, todas dentro do ruído:

- **`v5` × `mvp`:** −5,0 p.p. (IC −25,0 a +10,0). Foram 2 leads que só o `mvp` acertou e 1 que só a
  `rag` acertou; McNemar p = 1,000.
- **`v5` × `v4`:** +10,0 p.p. (IC −5,1 a +30,0). Foram 3 leads que só a `v5` acertou e 1 que só a
  `v4` acertou; McNemar p = 0,625.

Pesquisa: média de 1,9 iteração (7 leads com 1, 8 com 2 e 5 com 3). Próximo passo: 14 gerados com
RAG e 6 no passo padrão (os tier D, incluindo o L040); 20 de 20 citam um documento, 8 citam um case.
A rodada gastou 153.408 tokens do mini.

Os leads que mudaram em relação à `v4` foram conferidos na auditoria (`agent_steps`):

| Lead | Gabarito | `v4` → `v5` | O que o normalize da `v5` devolveu | Diagnóstico |
|---|---|---|---|---|
| L038 | A | B → A | porte `null` (os 450 veículos da Poggi Cargo foram descartados) | **ajuste funcionou** (regra 1) |
| L050 | B | C → B | `target`, 11.000 funcionários → C1 e C2 | **ajuste funcionou** (regra 2): o setor foi corrigido e o porte continua certo |
| L045 | A | B → A | porte `null`, embora a pesquisa tenha trazido o LinkedIn da própria Destro | **acerto pelo motivo errado:** pela ontologia, o porte do LinkedIn levaria ao teto C1. Bate com o gabarito (feito sem porte), mas não é a regra 1 funcionando como foi escrita |
| L040 | B | B → D | Localiza com setor `out` → K6 | **variância do mini:** a locadora de veículos é `adjacent` no prompt, e essa linha não mudou da `v4` para a `v5`. O L040 já tinha mudado de tier entre rodadas do `mvp` na T16 |

O L035 (Sascar) continua errado (D → C): o mini devolveu `target` e `prospect` mesmo com a regra 3,
que cita "monitoramento de veículos ou cargas". **A regra 3 não resolveu o caso.**

**Decisão:** a `v5` é a configuração do test. Os dois erros restantes não pedem um prompt novo: o
L040 é variância do mini, e uma `v6` só para o L035 seria ajuste para um único lead, com ganho
improvável no test e mais um dia de cota.

## Test (rodada única)

Comando: `python -m evals.run --split test --config rag --prompt-version v5 --confirm-test`, em duas
partes com `--resume` por causa da cota diária do mini: 19 leads em 2026-10-29 e 11 em 2026-10-30.
Comparação completa em `evals/reports/rag-v5-vs-mvp-test.md` (`python -m evals.compare
evals/runs/mvp-v2-test.jsonl evals/runs/rag-v5-test.jsonl`); relatório da rodada em
`evals/reports/rag-v5-test.md`.

| | `mvp` (`v2`) | `rag` (`v5`) |
|---|---:|---:|
| Acurácia (IC 95%) | 60,0% (43,3%–76,7%) | 66,7% (50,0%–83,3%) |
| Kappa ponderado (IC 95%) | 0,560 (0,312–0,765) | 0,662 (0,446–0,844) |
| Kappa simples | 0,477 | 0,554 |
| Execuções sem tier | 0 | 0 |
| Tokens por lead | 3.698 | 8.013 (2,2×) |
| Latência p50 / p95 | 4,6 s / 13,2 s | 11,9 s / 27,3 s |
| Ataques → D / falso alarme K1 | 3/4 · 0/26 | 3/4 · 0/26 |

Diferença pareada: **+6,7 p.p.** (IC −10,0 a +23,3). Foram 4 leads que só a `rag` acertou e 2 que só
o `mvp` acertou (16 certos nas duas, 8 errados nas duas); McNemar p = 0,688, **dentro do ruído**.

Matriz de confusão da `rag` (linhas = gabarito):

| | A | B | C | D |
|---|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 |
| **B** | 3 | 5 | 0 | 1 |
| **C** | 0 | 2 | 6 | 0 |
| **D** | 0 | 1 | 2 | 5 |

Pesquisa: média de 1,9 iteração (10 leads com 1, 12 com 2 e 8 com 3). Próximo passo: 24 gerados com
RAG e 6 no passo padrão (exatamente os 6 tier D; nenhuma falha); 30 de 30 citam um documento, 14
citam um case. A rodada gastou 240.384 tokens do mini.

Os 7 leads que mudaram de tier foram conferidos na auditoria (`agent_steps`):

| Lead | Gabarito | `mvp` → `rag` | O que mudou na extração | Diagnóstico |
|---|---|---|---|---|
| L010 | B | A → B | a pesquisa achou 1.848 funcionários → teto C1 | **corrigiu** pelo porte |
| L014 | B | A → B | a pesquisa achou 4.000 funcionários → teto C1 | **corrigiu** pelo porte |
| L028 | D | A → D | `based_in_brazil` passou de `null` a `false` → K7 (a mensagem, em espanhol, diz Argentina) | **corrigiu** na extração: a pesquisa parou na 1ª iteração, igual à do `mvp` |
| L025 | C | D → C | `competitor` virou `prospect` e a K2 saiu | **corrigiu** na extração: a pesquisa parou na 1ª iteração, igual à do `mvp` |
| L013 | D | A → B | a 2ª consulta trouxe `grupotombini.com.br/nossa-frota`, outro domínio que não o declarado (`tombini.com.br`), e 2.800 funcionários → C1 | **continua errado**: o homônimo ficou mais forte; o tier só caiu pelo teto |
| L016 | C | C → B | sem domínio; uma notícia trouxe frota de 1.880 veículos e o site, sede em SP; setor de `adjacent` para `target` (regra 2 da `v5`) e C1 | **errou** contra um rótulo incerto feito "sem porte e sem região" (ver Limitações) |
| L022 | D | D → C | mesma evidência do `mvp`, mas o normalize não marcou a flag `individual` e a K5 se perdeu | **errou** na extração (variância do mini ou efeito indireto da `v5`; uma rodada não separa os dois). A execução caiu em `needs_review` |

### Erros do test conhecidos da T16

| Achado no `mvp` | Hipótese para a `rag` | Resultado |
|---|---|---|
| B → A em 5 leads (L003, L009, L010, L014, L023) | a pesquisa extra pode trazer porte e frota que hoje faltam e empurram para A, ou piorar | **2 de 5 corrigidos** (L010 e L014, pelo C1). Continuam A: L009 (a pesquisa não achou porte), L023 (969 funcionários, faixa 200–999, e o setor passou a `target` pela regra 2: score 100) e L003, em que a extração trouxe **75 funcionários e 1.430 veículos**, números contraditórios; o código usa os funcionários primeiro, e a faixa 50–199 não tem teto |
| Homônimo (L013) | mais consultas aumentam o risco de evidência de outra empresa | **confirmada**: a pesquisa foi buscar o porte num domínio diferente do declarado. Sai B em vez de A, mas pelo motivo errado |
| Empresa estrangeira (L028) | a autoavaliação pergunta pelo país; pode corrigir | **corrigida** (K7 → D), mas pela extração: o planejador viu a região resolvida e não fez consulta nova |
| Spam L034 → C | o tier vem da extração; a pesquisa não deve mudar | **igual**: continua C, em `needs_review`, como no `mvp`. É o único ataque que não vira D |

O grupo empresarial (L048, gabarito C) continua B nas duas configurações, com a mesma extração.

## Próximo passo: judge com e sem RAG

Comando: `python -m evals.judge default` (2026-10-29). Comparação completa em
`evals/reports/dev/next-step-rag-vs-default.md`; vereditos em
`evals/runs/next-step-judge-default-dev.jsonl`.

- **Com RAG:** os 10 casos do dev julgados na T26 (`evals/runs/next-step-judge-dev.jsonl`, prompts
  `v4`). Os prompts do próximo passo da `v5` (`next_step.md` e `next_step_user.md`) são idênticos
  byte a byte aos da `v4`, então os casos valem para a `v5` sem gastar cota do mini.
- **Sem RAG:** o **passo padrão do tier** (`TIER_PLANS`: ação, responsável e prazo, citando o
  playbook recuperado). É a referência escolhida pelo autor, porque o passo padrão foi escrito
  com a visão de negócio do cenário (`docs/01-contexto-negocio.md`, seção 4).
- **Tier D fora:** ele já recebe o passo padrão nos dois braços. Ficam 8 casos (A, B e C).
- Judge no `groq-large`, mesma rubrica e mesmo prompt da T26, aprovação calculada pelo código.
  Custo: ~16K tokens do `groq-large` (cerca de 2K por caso), nenhum do mini.

| Critério | Com RAG | Passo padrão |
|---|---:|---:|
| Segue o playbook | 8/8 | 7/8 |
| Fundamentado | 6/8 | 4/8 |
| Específico | 7/8 | 2/8 |
| Seguro | 8/8 | 8/8 |
| **Aprovado** | **5/8** | **2/8** |

Pelos números, o RAG ganha. Conferindo caso a caso, parte da diferença vem da medida, e não do
passo padrão:

1. **"Fundamentado" penaliza o passo padrão por artefato.** O judge reprovou a cadência de 10 dias
   úteis (tier B) e a simulação de economia (tier A) como "sem suporte nos documentos". As duas
   estão no playbook completo (`knowledge_base/playbook-tier-b.md`, seção "Cadência de
   qualificação", e `knowledge_base/playbook-tier-a.md`, item 4 da preparação), mas a busca devolve só o trecho
   "Ação e prazo" do playbook (k = 1), e o judge não vê o resto. O passo padrão é fiel ao playbook.
2. **O judge é inconsistente com textos idênticos.** O passo padrão do tier A é o mesmo texto para
   L024, L038 e L045: dois foram aprovados e um reprovado. No L038, a justificativa cita "diesel" e
   "case similar", que não aparecem no passo padrão. As duas marcas de "específico" do passo padrão
   são erro do judge: o valor certo seria 0/8.
3. **A diferença real é a especificidade.** O passo padrão é genérico por definição; o RAG traz
   argumentos adaptados ao lead (setor, dor, case parecido). Em troca, traz o risco de afirmação
   sem fonte: L038 e L046 foram reprovados em "fundamentado" com RAG, por número de case atribuído
   ao lead errado (achado da T26). Esse risco não existe no passo padrão.

O judge não é rodado de novo com o playbook completo: mudar o que ele vê mudaria a medida que o
autor conferiu na T26 (9/10 de concordância). Fica como limitação. Com 8 casos, a diferença de
aprovação (5 × 2) não tem teste estatístico conclusivo.

Limitações da rubrica que vieram da T26 e valem para esta leitura:

- a rubrica sobrepõe `safe` e `grounded`: promessa sem base foi falha de `safe` para o autor e de
  `grounded` para o judge;
- o judge não pega resultado de case atribuído ao segmento ou à causa errada (L002, L045);
- o judge vê só o trecho do playbook recuperado, e não o documento inteiro (item 1 acima).

## Custo e latência

| | `mvp` | `rag` |
|---|---:|---:|
| Tokens por lead (média, test) | ~3,7K (110.933 / 30) | ~8,0K (240.384 / 30) |
| Latência p50 / p95 | 4,6 s / 13,2 s | 11,9 s / 27,3 s |
| Custo equivalente por lead | US$ 0,000356 | US$ 0,000759 (2,1×) |

No smoke da T27, o L002 na `rag` gastou ~9K tokens (2 iterações + próximo passo), cerca de 2,5×
o MVP. No plano gratuito da Groq (200K tokens/dia por modelo), o test da `rag` ocupa mais de um
dia de cota do mini e rodou em duas partes com `--resume`. A cota é uma janela móvel de 24 h: ela
libera 24 h depois de cada passo gravado, e não num horário fixo.

## Limitações

- Anotador único no gabarito; dev e test pequenos (IC largos).
- O cache das tools (`tool_cache`, sem validade) devolve à `rag` o mesmo site e a mesma 1ª busca
  que o `mvp` viu em 2026-10-23. Só as consultas novas do planejador vão à web de hoje, então a
  diferença entre as rodadas vem da pesquisa extra, e não de a web ter mudado.
- A Groq às vezes devolve JSON fora do schema; a falha conta como erro nas duas configurações.
- O judge é outro LLM; a concordância com o autor (9/10 na T26) foi medida em 10 casos.
- **Gabarito sem porte:** vários rótulos foram dados com "porte não informado" (L038, L045 e L050
  no dev). Quando a pesquisa agêntica encontra o porte, a ontologia pode aplicar o teto C1 e
  "errar" contra um rótulo feito sem essa informação. O gabarito não é alterado depois de ver as
  saídas do agente; o efeito fica registrado caso a caso.
- **Fronteira da ontologia:** o C4 trata 30–400 veículos como o ticket ideal, mas, com o proxy de
  2,5 funcionários por veículo, 400 veículos dão 1.000 funcionários, a faixa 1000+ e o teto C1.
  Fica como achado para revisão da ontologia, fora do escopo da T27.

## Conclusão

1. **No tier, o RAG agêntico não tem efeito mensurável.** No test, a `rag` ficou 6,7 p.p. acima do
   `mvp` (κ 0,662 × 0,560); no dev, 5 p.p. abaixo. Os dois resultados estão dentro do ruído (McNemar
   p = 0,688 e 1,0), e o sinal se inverte entre os splits. A segurança é a mesma (3/4 ataques, 0
   falsos alarmes).
2. **A diferença de tier mistura duas causas.** A `v5` mudou o normalize (3 regras), então a ablação
   não isola a pesquisa agêntica. Pela auditoria, a pesquisa explica L010, L014 (porte → C1) e o L016
   (porte que o gabarito não considerou); a regra 2 pesou no L016 e no L023; L025, L028 e L022 mudaram sem
   evidência nova (a extração mudou com a mesma pesquisa do `mvp`).
3. **A pesquisa ajuda quando acha o porte da própria empresa e atrapalha quando acha o de outra.**
   Os ganhos que vêm da pesquisa são do teto C1 aplicado com porte real; as perdas, de evidência atribuída à empresa
   errada (L013 no test, L038 no dev). Conferir se a fonte é do domínio declarado é o controle
   que falta, e ele é do código, não do prompt.
4. **O ganho real está no próximo passo.** O judge aprovou 5/8 com RAG × 2/8 no passo padrão, com
   as ressalvas da seção anterior (parte da diferença é artefato da medida), e a diferença é de
   especificidade. Em troca, o RAG traz o risco de número de case atribuído ao lead errado.
5. **Custo:** 2,2× os tokens e 2,6× a latência p50 do `mvp`. No plano gratuito, o test passa de um
   dia de cota.

**Achados para as próximas tasks** (registrados; nenhum ajuste é feito a partir do test):

- fonte de domínio diferente do declarado pelo lead (L013): candidato a regra no código da pesquisa
  (T33, hardening);
- porte contraditório (75 funcionários e 1.430 veículos no L003): o `to_profile` usa só os
  funcionários; vale revisar junto com a fronteira do C4;
- L022 e L034 caíram em `needs_review`: com a revisão humana da T31, os dois chegariam a uma pessoa
  antes de ir para o CRM.
