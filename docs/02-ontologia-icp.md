# 02 · Ontologia do ICP e rubrica de pontuação

Este documento é a **fonte única de verdade** da qualificação. Ele é usado:
1. pelo código (`app/ontology/rubric.yaml` + `scoring.py`, a partir da T06/T07);
2. pelos prompts do agente (para mapear evidências aos conceitos);
3. pelos anotadores humanos na rotulagem do dataset (T09).

## 1. Princípio
> **O LLM extrai, o código pontua.**
> O agente só informa **valores da ontologia** (ex.: `Sector = target`, `SizeBand = 50-199`), cada um com evidência e fonte.
> A pontuação, os tetos e o tier são calculados de forma **determinística** pela rubrica abaixo.

*Refinamento em relação à arquitetura:* em vez de o LLM atribuir níveis genéricos (`strong/partial/none`) por critério, ele devolve o **valor ontológico**, e a rubrica converte esse valor em pontos. Assim o LLM tem menos espaço para "opinar", e a regra de negócio fica 100% testável.

## 2. Conceitos e relações

```
Lead ──hasCompany──► Company ──inSector──► SectorFit      {target, adjacent, out, unknown}
  │                    ├──hasSize─────► SizeBand         {1-49, 50-199, 200-999, 1000+, unknown}
  │                    ├──locatedIn───► RegionFit        {priority, secondary, abroad, unknown}
  │                    └──isA─────────► CompanyKind      {prospect, competitor, vendor, unknown}
  ├──hasContact──► Contact ──hasRole──► Role
  │                                      ├── Area        {operations, logistics, fleet, finance, executive, it,
  │                                      │                procurement, sales, marketing, hr, legal, other, unspecified}
  │                                      ├── Seniority   {c_level, owner, director, manager, coordinator,
  │                                      │                analyst, intern, unknown}
  │                                      └── BuyingRole  {decision_maker, influencer, user, none, unknown}  ← derivado
  ├──expresses──► IntentSignal  {pain, pricing_request, vendor_switch, curiosity, none}
  └──flaggedAs──► LeadFlag      {student, job_seeker, individual, spam, injection}
```

### 2.1 Taxonomias
| Conceito | Valor | Regra de mapeamento |
|---|---|---|
| **SectorFit** | `target` | CNAE 49.30-2 (transporte rodoviário de cargas) ou 46.xx (atacado/distribuição com entrega própria) |
| | `adjacent` | CNAE 52.11, 52.50 (logística/armazenagem); 01.xx (agro); 41–43 (construção); 36–39 (saneamento/resíduos); 35 (energia) e 61 (telecom) com equipe de campo; 77.11 (locadoras) |
| | `out` | Qualquer outro setor (software, financeiro, varejo B2C, educação, saúde...) |
| **SizeBand** | faixas por nº de funcionários | Estimado por evidência pública; quando houver só a frota, usar `≈ 2,5 funcionários por veículo` como proxy e marcar a certeza como `low` |
| **RegionFit** | `priority` | Sede ou operação principal no Sudeste, Sul ou Centro-Oeste |
| | `secondary` | Norte ou Nordeste |
| | `abroad` | Fora do Brasil |
| **CompanyKind** | `competitor` | Empresa de telemetria, rastreamento ou software de frota |
| | `vendor` | O lead quer **vender** algo para a FrotaSense (agência, consultoria, fornecedor) |
| **IntentSignal** | `pain` / `pricing_request` / `vendor_switch` | Dor explícita, pedido de preço/proposta/demo, troca de fornecedor |
| | `curiosity` | Interesse genérico ("quero conhecer") |
| | `none` | Mensagem vazia ou sem intenção |

### 2.2 Derivação de `BuyingRole` (tabela, sem LLM)
| Seniority \ Area | operations, logistics, fleet | finance, executive, unspecified | it, procurement | sales, marketing, hr, legal, other |
|---|---|---|---|---|
| **c_level, owner** | decision_maker | decision_maker | influencer | none |
| **director** | decision_maker | decision_maker | influencer | none |
| **manager** | decision_maker | influencer | influencer | none |
| **coordinator** | influencer | influencer | influencer | none |
| **analyst** | user | user | user | none |
| **intern** | none | none | none | none |
| **unknown** | unknown | unknown | unknown | none |

Para **c_level/owner**, a área `executive` cobre CEO, sócio e fundador. Um cargo **sem área explícita** ("Diretor", "Diretor-geral", "Sócio") recebe a área `unspecified`, que é tratada como executiva: diretor ou sócio sem área é **decisor**. Já cargos com área administrativa ("Gerente Administrativo") continuam como `other`. A FrotaSense é uma compra operacional e financeira, então Comercial, Marketing, RH e Jurídico não têm papel na decisão.

## 3. Rubrica de pontuação

### 3.1 Critérios e pesos (soma = 100)
| Critério | Peso | Valores → fator |
|---|---:|---|
| **Setor** (`SectorFit`) | **30** | target 1,0 · adjacent 0,5 · out 0,0 · unknown 0,25 |
| **Papel na compra** (`BuyingRole`) | **25** | decision_maker 1,0 · influencer 0,6 · user 0,3 · none 0,0 · unknown 0,3 |
| **Porte** (`SizeBand`) | **20** | 50-199 1,0 · 200-999 1,0 · 1000+ 0,5 · 1-49 0,2 · unknown 0,3 |
| **Intenção** (`IntentSignal`) | **15** | pain / pricing_request / vendor_switch 1,0 · curiosity 0,4 · none 0,0 |
| **Região** (`RegionFit`) | **10** | priority 1,0 · secondary 0,6 · abroad 0,0 · unknown 0,5 |

**Score** = Σ (peso × fator), na faixa de 0 a 100, arredondado para 1 casa decimal.
Quando há mais de um sinal de intenção, vale o de maior fator.

### 3.2 Tiers por score
| Tier | Faixa |
|---|---|
| **A** | score ≥ 75 |
| **B** | 55 ≤ score < 75 |
| **C** | score < 55 |
| **D** | só por regra eliminatória (3.3) |

**Fronteira:** quando o score fica a até **5 pontos** de um limite (75 ou 55), o resultado recebe `is_borderline = true`. Isso aciona o escalonamento para o modelo maior no roteador (T29).

### 3.3 Regras eliminatórias (resultado = D, em ordem de precedência)
| # | Condição | Motivo registrado |
|---|---|---|
| K1 | `LeadFlag ∈ {spam, injection}` | `spam_or_manipulation` |
| K2 | `CompanyKind = competitor` | `competitor` |
| K3 | `CompanyKind = vendor` | `vendor_pitch` |
| K4 | `LeadFlag ∈ {student, job_seeker}` | `not_a_buyer` |
| K5 | `LeadFlag = individual` | `individual_b2c` |
| K6 | `SectorFit = out` | `out_of_sector` |
| K7 | `RegionFit = abroad` | `out_of_region` |

Basta uma regra disparar. Todas as regras disparadas são registradas, mas o motivo principal é a de menor número.

### 3.4 Tetos de tier (aplicados após o score)
| # | Condição | Teto | Justificativa de negócio |
|---|---|---|---|
| C1 | `SizeBand = 1000+` | **B** | Enterprise tem ciclo longo e vai para um processo próprio, com qualificação de SDR antes do AE |
| C2 | `BuyingRole ∉ {decision_maker, influencer}` | **B** | Tier A exige papel relevante na compra |
| C3 | `BuyingRole = none` | **C** | Sem papel na compra, o lead vai para nutrição |
| C4 | `SizeBand = 1-49` | **B** | Frota pequena tem ticket abaixo do ideal (30–400 veículos): vai para o SDR, nunca direto para o AE |

Tier final = o **pior** entre o tier do score e os tetos aplicáveis (ordem A > B > C > D).

### 3.5 Incerteza
- Cada valor extraído traz `certainty ∈ {high, medium, low}`.
- `needs_human_review = true` quando **dois ou mais** dos critérios Setor, Porte e Papel estão `unknown` ou com certeza `low`, **e** o resultado não é D por regra eliminatória. (O nó de revisão humana entra na T31.)

## 4. Exemplos calculados à mão (viram testes na T07)

| # | Lead | Setor | Papel | Porte | Intenção | Região | Score | Regras | Tier |
|---|---|---|---|---|---|---|---:|---|:-:|
| E1 | Transportadora, 120 func., SP · Diretor de Operações · "Quero proposta para 80 caminhões" | target 30 | director×operations → decision_maker 25 | 50-199 20 | pricing_request 15 | priority 10 | **100,0** | — | **A** |
| E2 | Distribuidora de bebidas, 400 func., PR · Coordenador de Frota · "Gostaria de conhecer a plataforma" | target 30 | coordinator×fleet → influencer 15 | 200-999 20 | curiosity 6 | priority 10 | **81,0** | — | **A** |
| E3 | Operador logístico (armazenagem), 300 func., MG · Gerente de Logística · "Perdemos controle do diesel" | adjacent 15 | manager×logistics → decision_maker 25 | 200-999 20 | pain 15 | priority 10 | **85,0** | — | **A** |
| E4 | Transportadora, 2.500 func., RJ · CFO · "Queremos uma demo" | target 30 | c_level×finance → decision_maker 25 | 1000+ 10 | pricing_request 15 | priority 10 | **90,0** | C1 → teto B | **B** |
| E5 | Transportadora, 30 func., BA · Sócio · "Quero conhecer" | target 30 | owner×executive → decision_maker 25 | 1-49 4 | curiosity 6 | secondary 6 | **71,0** | C4 → teto B | **B** (borderline: 71 está a 4 de 75) |
| E6 | Distribuidora, 150 func., SC · Estagiário de Logística · "Pesquisando ferramentas" | target 30 | intern → none 0 | 50-199 20 | curiosity 6 | priority 10 | **66,0** | C3 → teto C | **C** |
| E7 | Construtora, 250 func., GO · Analista de Compras · (mensagem vazia) | adjacent 15 | analyst×procurement → user 7,5 | 200-999 20 | none 0 | priority 10 | **52,5** | — | **C** (borderline: 52,5 está a 2,5 de 55) |
| E8 | Empresa de rastreamento veicular, 90 func., SP · Gerente Comercial · "Gostaria de conhecer a solução de vocês" | (out) | sales → none | 50-199 | curiosity | priority | — | K2 `competitor` (também K6) | **D** |

### Verificação manual (gate da T02)
- Soma dos pesos: 30 + 25 + 20 + 15 + 10 = **100** ✔
- E1: 30 + 25 + 20 + 15 + 10 = 100 → A ✔
- E2: 30 + 25×0,6 + 20 + 15×0,4 + 10 = 30 + 15 + 20 + 6 + 10 = 81 → A (papel influencer passa no C2) ✔
- E3: 30×0,5 + 25 + 20 + 15 + 10 = 15 + 25 + 20 + 15 + 10 = 85 → A ✔
- E4: 30 + 25 + 20×0,5 + 15 + 10 = 90 → A pelo score; teto C1 → **B** ✔
- E5: 30 + 25 + 20×0,2 + 15×0,4 + 10×0,6 = 30 + 25 + 4 + 6 + 6 = 71 → B; teto C4 (B) aplicado sem efeito; |75 − 71| = 4 ≤ 5 → borderline ✔
- E6: 30 + 0 + 20 + 6 + 10 = 66 → B pelo score; tetos C2 (B) e C3 (C) → **C** ✔
- E7: 15 + 25×0,3 + 20 + 0 + 10 = 15 + 7,5 + 20 + 0 + 10 = 52,5 → C; |55 − 52,5| = 2,5 ≤ 5 → borderline ✔
- E8: K2 (competitor) dispara primeiro; K6 também é registrada → **D** ✔
- Todo exemplo cai em exatamente um tier, e os 4 tiers estão representados ✔

## 5. Guia rápido para anotadores humanos (T09)
1. Leia apenas o lead e as evidências públicas (site, busca). **Não** veja a saída do agente.
2. Preencha os valores ontológicos (setor, porte, região, cargo → área/senioridade, intenção, flags).
3. Aplique as regras eliminatórias, depois a rubrica, depois os tetos.
4. Registre o tier e uma justificativa curta, e marque `uncertain` se faltar evidência.
