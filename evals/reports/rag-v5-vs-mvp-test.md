# RAG agêntico (v5) × MVP (test)

- **Split:** test (30 leads em comum)
- **Configurações:** mvp (`v2`) × rag (`v5`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | rag (`v5`) |
|---|---:|---:|
| Acurácia (IC 95%) | 60.0% (43.3% – 76.7%) | 66.7% (50.0% – 83.3%) |
| Kappa ponderado linear (IC 95%) | 0.560 (0.312 – 0.765) | 0.662 (0.446 – 0.844) |
| Kappa simples | 0.477 | 0.554 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000356 | 0.000759 |
| Tokens por lead (entrada + saída) | 3,698 | 8,013 |
| Latência p50 / p95 (s) | 4.6 / 13.2 | 11.9 / 27.3 |
| Ataques desqualificados (D) | 3/4 | 3/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de rag − mvp:** +6.7% (IC 95% por bootstrap: -10.0% a +23.3%).
- **Pares:** 16 certos nas duas, 8 errados nas duas, 4 só rag acertou, 2 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 0.688. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (7)

| Lead | Gabarito | mvp | rag | Efeito |
|---|---|---|---|---|
| L010 | B | A | B | corrigiu |
| L013 | D | A | B | trocou |
| L014 | B | A | B | corrigiu |
| L016 | C | C | B | errou |
| L022 | D | D | C | errou |
| L025 | C | D | C | corrigiu |
| L028 | D | A | D | corrigiu |

## Matriz de confusão de rag (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 3 | 5 | 0 | 1 | 0 |
| **C** | 0 | 2 | 6 | 0 | 0 |
| **D** | 0 | 1 | 2 | 5 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (30 execuções): 1 iteração(ões): 10 · 2 iteração(ões): 12 · 3 iteração(ões): 8 (média 1.93).
- **Próximo passo** (30 execuções com tier): 24 gerados com RAG e 6 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 30 de 30 citam pelo menos um documento; 14 citam um case; 10 documentos diferentes citados.
- **Mais citados:** `playbook-tier-b` (9), `case-transportadora-serra-azul` (9), `playbook-tier-c` (8), `playbook-tier-a` (7), `case-rodo-cerrado-cargas` (7).
