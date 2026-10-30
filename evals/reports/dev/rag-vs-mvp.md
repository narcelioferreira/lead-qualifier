# RAG agêntico × MVP (dev)

- **Split:** dev (20 leads em comum)
- **Configurações:** mvp (`v2`) × rag (`v4`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | rag (`v4`) |
|---|---:|---:|
| Acurácia (IC 95%) | 95.0% (85.0% – 100.0%) | 80.0% (60.0% – 95.0%) |
| Kappa ponderado linear (IC 95%) | 0.961 (0.864 – 1.000) | 0.837 (0.660 – 0.959) |
| Kappa simples | 0.933 | 0.734 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000358 | 0.000727 |
| Tokens por lead (entrada + saída) | 3,698 | 7,761 |
| Latência p50 / p95 (s) | 2.7 / 16.6 | 7.1 / 19.7 |
| Ataques desqualificados (D) | 3/3 | 3/3 |
| Falso alarme K1 em lead legítimo | 0/17 | 0/17 |

## Diferença pareada (mesmos leads)

- **Acurácia de rag − mvp:** -15.0% (IC 95% por bootstrap: -35.0% a +5.0%).
- **Pares:** 15 certos nas duas, 0 errados nas duas, 1 só rag acertou, 4 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 0.375. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (5)

| Lead | Gabarito | mvp | rag | Efeito |
|---|---|---|---|---|
| L021 | A | B | A | corrigiu |
| L035 | D | D | C | errou |
| L038 | A | A | B | errou |
| L045 | A | A | B | errou |
| L050 | B | B | C | errou |

## Matriz de confusão de rag (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 3 | 2 | 0 | 0 | 0 |
| **B** | 0 | 4 | 1 | 0 | 0 |
| **C** | 0 | 0 | 4 | 0 | 0 |
| **D** | 0 | 0 | 1 | 5 | 0 |

## Pesquisa agêntica e próximo passo

- **Iterações da pesquisa** (20 execuções): 1 iteração(ões): 6 · 2 iteração(ões): 8 · 3 iteração(ões): 6 (média 2.00).
- **Próximo passo** (20 execuções com tier): 15 gerados com RAG e 5 no passo padrão do tier (tier D, falha ou sem citação válida).
- **Citações:** 20 de 20 citam pelo menos um documento; 10 citam um case; 12 documentos diferentes citados.
- **Mais citados:** `playbook-tier-b` (6), `playbook-tier-c` (6), `playbook-tier-d` (5), `case-transportadora-serra-azul` (4), `playbook-tier-a` (3).
