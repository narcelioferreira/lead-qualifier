# Avaliação final: configuração `api` (T34)

- **Configuração:** `api`, a mesma montagem que a API usa: grafo do MVP, prompts `v6` e guardrail, sem pesquisa agêntica, próximo passo nem política de roteamento
- **Splits:** dev (20 leads) e test (30 leads, rodada **única** com `--confirm-test`, depois do congelamento)
- **Gabarito:** rotulagem humana (T09), anotador único: sem kappa humano de referência
- **Integridade:** os 30 leads do test rodaram com o digest `3bb59143…`, o mesmo do congelamento (registrado no `audit_log` de cada execução)
- **Gerado em:** 2026-11-10

## Resultado

**No test, a configuração entregue acertou 60,0% dos leads (κ ponderado 0,610), desqualificou os 4 ataques e não barrou nenhum lead legítimo, a US$ 0,00043 por lead.** No dev, onde os prompts foram calibrados, ela fez 95,0%. A distância entre os dois números é o principal resultado desta avaliação: o ajuste no dev não generalizou por inteiro, como já tinha acontecido com o `mvp` na T16.

| Split | Acurácia (IC 95%) | κ ponderado (IC 95%) | Ataques desqualificados | Falso alarme K1 | Custo por lead | Tokens por lead | Latência p50 / p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| dev (20) | 95,0% | 0,961 | 3/3 | 0/17 | US$ 0,000422 | 4.424 | 10,6 s / 19,7 s |
| **test (30)** | **60,0% (43,3%–76,7%)** | **0,610 (0,401–0,804)** | **4/4** | **0/26** | **US$ 0,000434** | **4.507** | **9,2 s / 20,7 s** |

O custo é **equivalente**, calculado pelo preço de lista: as rodadas usaram o plano gratuito da Groq. Todos os tokens foram do `groq-mini` (135.209 no test): 27 checagens do guardrail (os 3 leads barrados pela regra não chamam modelo), 26 extrações e 26 justificativas. O SLM de reserva do guardrail não foi acionado.

### Matriz de confusão no test (linhas = gabarito, colunas = agente)

| | A | B | C | D |
|---|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 |
| **B** | 5 | 3 | 0 | 1 |
| **C** | 0 | 2 | 5 | 1 |
| **D** | 1 | 0 | 1 | 6 |

- **B é a classe mais fraca:** revocação de 33,3% (3 de 9). Cinco leads B saíram A.
- **A tem revocação alta e precisão baixa:** 4 de 5 leads A acertados, mas só 4 das 10 previsões A estavam certas.
- **Nenhuma execução falhou**, e nenhum lead ficou sem tier.

## O que está sendo medido

- **O tier antes de qualquer decisão humana.** Sem `checkpointer`, a execução não para: o lead incerto sai com o tier calculado e status `needs_review`. Na API, esse lead esperaria uma pessoa.
- **Sem CRM.** A avaliação não grava no HubSpot.
- **Sem cache de LLM.** As chamadas à Groq são feitas a cada execução. O cache das ferramentas (Tavily e sites) vale como na API.

## Comparação com as rodadas anteriores

Mesmos 30 leads, com diferença pareada e McNemar exato (`evals/compare.py`).

| Comparação | Diferença de acurácia (IC 95%) | Só a 1ª acertou / só a 2ª acertou | McNemar p |
|---|---:|---:|---:|
| `api` − `mvp` | 0,0 p.p. (−13,3 a +13,3) | 2 / 2 | 1,000 |
| `api` − `routing` | −10,0 p.p. (−23,3 a 0,0) | 0 / 3 | 0,250 |

- **Contra o `mvp` (T16):** a mesma acurácia, com outros acertos. A `api` passou a acertar o L028 (empresa estrangeira, K7 com os prompts `v6`) e o L034 (spam barrado pelo guardrail), e errou o L016 e o L022, que o `mvp` acertava.
- **Contra a `routing` (T30):** a `routing` acertou L022, L025 e L049, que a `api` errou, e as duas erraram o L013 (com tiers diferentes). A diferença não sai do ruído (p = 0,25). A `routing` tem a pesquisa agêntica, o próximo passo e o escalonamento da extração para o modelo maior (o L022 escalou na T30), a cerca de 2,2× o custo e 4,5× a latência p50.
- **Nenhuma comparação no test chegou a p < 0,05.** Com 30 leads, cada lead vale 3,3 pontos percentuais.

Relatórios: `api-test.md`, `api-v6-vs-mvp-test.md`, `api-v6-vs-routing-test.md` e, no dev, `dev/api-v6.md`.

## Análise de erros

A `api` errou 12 dos 30 leads. Cada divergência foi conferida no perfil extraído (`agent_steps`, nó `normalize`), nos critérios pontuados e na justificativa do gabarito. Os erros ficam registrados e **não viram ajuste**: depois de ver o test, nada foi alterado nem rodado de novo.

| Lead | Gabarito | `api` | Score | Causa | Sinal na execução |
|---|---|---|---:|---|---|
| L009 | B | A | 86,0 | Porte não encontrado: sem o teto C1 | — |
| L010 | B | A | 81,0 | Porte não encontrado: sem o teto C1 | — |
| L014 | B | A | 81,0 | Porte não encontrado: sem o teto C1 | — |
| L003 | B | A | 76,0 | Evidência que o gabarito não usou (região SC) | fronteira |
| L023 | B | A | 100,0 | Evidência que o gabarito não usou (969 funcionários) | — |
| L044 | A | B | 90,0 | Evidência que o gabarito não usou (1.400 funcionários → C1) | — |
| L013 | D | A | 77,0 | Setor escolhido pelo LLM sem CNAE: fabricante de móveis como alvo | fronteira |
| L049 | B | D | 56,0 | Setor escolhido pelo LLM sem CNAE: telecom como fora do setor (K6) | — |
| L022 | D | C | 39,0 | Flag `individual` não marcada: K5 perdida | revisão humana |
| L025 | C | D | 28,5 | Locadora de frotas classificada como concorrente (K2) | — |
| L048 | C | B | 56,0 | "Gerente Administrativo" mapeado como influenciador | fronteira |
| L016 | C | B | 62,0 | Perfil igual ao da justificativa do gabarito, tier diferente | — |

### 1. Porte não encontrado: o teto C1 não se aplica (3 leads, B → A)

**Leads:** L009 (Patrus), L010 (Reiter Log) e L014 (Martins Atacado).

- **O que aconteceu:** o gabarito marca as três como enterprise, o que aplica o teto C1 (máximo B). A pesquisa da `api` (home, página "sobre" e uma busca) não trouxe o número de funcionários nem a frota. O porte ficou `unknown` (6 de 20 pontos) e, sem porte, o teto não entra: com setor-alvo, decisor e intenção forte, o score passa de 75.
- **Por que importa:** a rubrica trata porte desconhecido como neutro, mas o teto C1 só vale com porte conhecido. Uma empresa grande sem porte na evidência sai melhor que a mesma empresa com o porte conhecido.
- **Evidência de que a pesquisa resolve parte:** na `rag` (T27), com a pesquisa agêntica, o L010 e o L014 saíram B. O loop pergunta o que falta e busca o porte de novo.
- **Correção proposta:** (a) ligar na API uma busca dirigida ao porte quando ele não aparecer, ou a pesquisa agêntica, medindo antes no dev; ou (b) decidir na rubrica se porte desconhecido com score A deve ir para revisão. Qualquer uma das duas é configuração nova e precisa de rodada própria.

### 2. Evidência que o gabarito não usou (3 leads)

**Leads:** L003 (Dalçoquio), L023 (Loga) e L044 (Della Volpe). **Os três estão marcados como incertos no gabarito.**

- **L003 (B → A):** a justificativa do gabarito não cita a região. O agente achou a UF (SC, prioritária) na evidência, o que soma 10 pontos em vez de 5 e leva o score a 76, 1 ponto acima do corte de A. A execução marcou fronteira. O site também deu timeout (`site: home: timeout`), e o perfil veio da busca.
- **L023 (B → A):** o gabarito diz "porte não informado". O agente achou 969 funcionários (faixa 200–999, nota máxima) e chegou a 100.
- **L044 (A → B):** o gabarito diz "porte não informado". O agente achou 1.400 funcionários, e a rubrica aplicou o teto C1.
- **Leitura:** nesses três, o agente seguiu a rubrica com uma evidência que o rotulador não tinha à mão. Não dá para dizer, só com os dados da avaliação, se a evidência está certa. As outras quatro configurações deram o mesmo tier da `api` nesses três leads.
- **Encaminhamento:** decisão do autor. O gabarito não foi alterado. Se algum rótulo for revisto depois de ver o test, a revisão precisa ser registrada como tal, e o número oficial desta rodada continua sendo 60,0%.

### 3. Setor escolhido pelo LLM, sem CNAE (2 leads)

**Leads:** L013 (Tombini, D → A) e L049 (Brisanet, B → D).

- **Achado geral:** o código só fixa o setor pelo CNAE quando o CNAE aparece nas evidências. **No test, isso aconteceu em 2 dos 26 leads que chegaram à extração, e os dois são empresas fictícias com site simulado** (L018 e L037). Nas empresas reais, o setor veio sempre da classificação do LLM, com a certeza que ele mesmo declarou.
- **L013:** fabricante de mobiliário corporativo. As fontes eram do domínio declarado, mas a mensagem fala em "frota de entregas", e o mini classificou o setor como alvo com certeza alta. Score 77, na fronteira. Na T27 e na T30, o mesmo lead foi tratado como homônimo; aqui as fontes eram do domínio certo, e o erro está na classificação.
- **L049:** provedor de internet com "centenas de veículos de técnicos de campo". O gabarito trata como operação de campo adjacente (B). O mini classificou como fora do setor, e a K6 desqualificou. A `routing` deu B.
- **Correção proposta:** pedir o CNAE na busca (por exemplo, numa consulta ao cadastro público da empresa) e tratar o setor sem CNAE como certeza média, como já acontece com o CNAE que só o lead declarou. Isso muda o comportamento e precisa ser medido no dev.

### 4. Regras eliminatórias que dependem de classificação do LLM (2 leads)

- **L022 (D → C):** caminhoneiro autônomo com 1 caminhão pedindo preço "pra pessoa física". O mini não marcou a flag `individual`, e a K5 não entrou. As outras quatro configurações acertaram D, então o caso é variância da extração. **A execução pediu revisão humana** (dois critérios críticos incertos): na API, ela pararia em `needs_review`, e uma pessoa veria o caso.
- **L025 (C → D):** analista jurídico da Unidas perguntando sobre LGPD. O mini classificou a Unidas, que é locadora e faz terceirização de frotas, como concorrente, e a K2 desqualificou. O gabarito dá C pelo cargo sem papel na compra. A `mvp` e a `large_only` também deram D, e a `rag` e a `routing`, C. **A taxonomia não diz se locadora de frota é concorrente**, e as configurações se dividem.
- **Correção proposta:** para a K5, uma regra determinística sobre o texto do lead ("pessoa física", "autônomo", CPF) antes do LLM, com teste de falso positivo. Para a K2, uma lista de concorrentes e de categorias adjacentes na taxonomia, decidida pelo autor.

### 5. Mapeamento de cargo (1 lead)

- **L048 (C → B):** "Gerente Administrativo" do Grupo Brasal. O mini deu área `unspecified`, e a matriz de `buying_roles.yaml` agrupa `unspecified` com finanças e executivo: gerente nesse grupo vira influenciador (15 pontos). O score ficou em 56, 1 ponto acima do corte de B, e a execução marcou fronteira. O gabarito diz que o cargo "não tem papel mapeável".
- **Correção proposta:** decidir se "administrativo" deve ter área própria na taxonomia. É mudança de regra de negócio e é do autor.

### 6. Perfil igual ao da justificativa, tier diferente (1 lead)

- **L016 (C → B):** "Ativa Logística", sem domínio, coordenador de logística, "Gostaria de conhecer." O perfil extraído coincide com a justificativa do gabarito: operador logístico, coordenador influenciador, interesse genérico, porte e região não informados. Pela rubrica, esse perfil soma 30 + 15 + 6 + 6 + 5 = 62, o que dá B. O gabarito dá C e está marcado como incerto.
- **Leitura:** pode ser que o rotulador tenha descontado o setor por falta de domínio, o que a justificativa não diz. O `mvp` deu C nesse lead.
- **Encaminhamento:** conferência do autor, nas mesmas condições do grupo 2.

## Sinais de incerteza

Dos 12 erros, 4 tiveram algum sinal na execução: o L022 pediu revisão humana, e o L003, o L013 e o L048 ficaram na fronteira de tier (até 5 pontos do corte). Entre os 18 acertos, só o L041 ficou na fronteira, e nenhum pediu revisão.

- **Hoje, na API, só a revisão para a execução.** A fronteira fica registrada, mas o tier sai direto.
- **Proposta:** mandar para a revisão também os leads na fronteira. No test, isso teria levado 3 erros e 1 acerto a uma pessoa. A mudança precisa ser medida no dev, porque aumenta a fila de revisão.
- **Os outros 8 erros não tiveram sinal.** São os casos mais caros, porque o tier errado chega ao CRM com confiança alta: os três de porte não encontrado (grupo 1) saíram com confiança 0,733, e o L023 e o L044, com 1,0.

## Segurança

| Métrica | Test |
|---|---:|
| Ataques desqualificados (D) | 4/4 |
| Detectados pela regra determinística, sem LLM | 3/4 |
| Falso alarme K1 em lead legítimo | 0/26 |

- O L034 (spam) foi barrado pelo guardrail no mini. No `mvp` e na `rag`, ele saía C.
- São 4 ataques: o resultado mostra o comportamento nesses casos, sem estimar uma taxa.

## Ressalvas da execução

- **Rodada em duas partes:** 12 leads em 06/11 e 18 em 10/11 (UTC). A primeira parte foi interrompida sem falha registrada. Entre as duas, nada mudou em `app/` nem em `evals/run.py`, e o digest de integridade foi o mesmo nos 30 leads. A retomada usou `--resume` no mesmo arquivo, sem refazer nenhum lead.
- **Variância das ferramentas:** a busca e os sites são reais, com cache. Uma nova execução sem cache pode trazer outra evidência, como mostram L003 (timeout do site) e os casos de porte.
- **Gabarito:** anotador único. Seis dos 12 erros estão em leads marcados como incertos no gabarito.
- **Amostra:** 30 leads, com intervalos largos (a acurácia vai de 43% a 77% no IC 95%).

## Reprodução

O arquivo de previsões é o cache da rodada. Retomá-lo não refaz nenhum lead e gera de novo o relatório. Conferido em 10/11: o relatório saiu idêntico (fora a data de geração), sem nenhum passo novo em `agent_steps` e com o SHA-256 do arquivo de previsões inalterado.

```bash
uv run python -m evals.run --split test --config api --prompt-version v6 --confirm-test --resume evals/runs/api-v6-test.jsonl --report evals/reports/api-test.md
uv run python -m evals.compare evals/runs/mvp-v2-test.jsonl evals/runs/api-v6-test.jsonl --out evals/reports/api-v6-vs-mvp-test.md --title "api × mvp (test)" --names mvp api
uv run python -m evals.compare evals/runs/routing-v6-test.jsonl evals/runs/api-v6-test.jsonl --out evals/reports/api-v6-vs-routing-test.md --title "api × routing (test)" --names routing api
```

A análise de erros usa o perfil extraído e os critérios de cada execução, gravados em `agent_runs` e `agent_steps` pelo `run_id` de cada linha do arquivo de previsões.
