# api × routing (test)

- **Split:** test (30 leads em comum)
- **Configurações:** routing (`v6`) × api (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | routing (`v6`) | api (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 70.0% (53.3% – 86.7%) | 60.0% (43.3% – 76.7%) |
| Kappa ponderado linear (IC 95%) | 0.733 (0.555 – 0.887) | 0.610 (0.401 – 0.804) |
| Kappa simples | 0.602 | 0.474 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000968 | 0.000434 |
| Tokens por lead (entrada + saída) | 9,230 | 4,507 |
| Latência p50 / p95 (s) | 41.4 / 63.9 | 9.2 / 20.7 |
| Ataques desqualificados (D) | 4/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de api − routing:** -10.0% (IC 95% por bootstrap: -23.3% a +0.0%).
- **Pares:** 18 certos nas duas, 9 errados nas duas, 0 só api acertou, 3 só routing acertou.
- **McNemar exato** (pares discordantes): p = 0.250. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (4)

| Lead | Gabarito | routing | api | Efeito |
|---|---|---|---|---|
| L013 | D | B | A | trocou |
| L022 | D | D | C | errou |
| L025 | C | C | D | errou |
| L049 | B | B | D | errou |

## Matriz de confusão de api (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 3 | 0 | 1 | 0 |
| **C** | 0 | 2 | 5 | 1 | 0 |
| **D** | 1 | 0 | 1 | 6 | 0 |
