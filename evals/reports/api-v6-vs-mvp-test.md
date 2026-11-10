# api × mvp (test)

- **Split:** test (30 leads em comum)
- **Configurações:** mvp (`v2`) × api (`v6`)
- **Gabarito:** rotulagem humana (T09), anotador único

## Lado a lado

| Métrica | mvp (`v2`) | api (`v6`) |
|---|---:|---:|
| Acurácia (IC 95%) | 60.0% (43.3% – 76.7%) | 60.0% (43.3% – 76.7%) |
| Kappa ponderado linear (IC 95%) | 0.560 (0.312 – 0.765) | 0.610 (0.401 – 0.804) |
| Kappa simples | 0.477 | 0.474 |
| Execuções sem tier | 0 | 0 |
| Custo médio por lead (US$) | 0.000356 | 0.000434 |
| Tokens por lead (entrada + saída) | 3,698 | 4,507 |
| Latência p50 / p95 (s) | 4.6 / 13.2 | 9.2 / 20.7 |
| Ataques desqualificados (D) | 3/4 | 4/4 |
| Falso alarme K1 em lead legítimo | 0/26 | 0/26 |

## Diferença pareada (mesmos leads)

- **Acurácia de api − mvp:** +0.0% (IC 95% por bootstrap: -13.3% a +13.3%).
- **Pares:** 16 certos nas duas, 10 errados nas duas, 2 só api acertou, 2 só mvp acertou.
- **McNemar exato** (pares discordantes): p = 1.000. Com essa amostra, a diferença **não** se distingue do ruído.

## Leads em que o tier mudou (4)

| Lead | Gabarito | mvp | api | Efeito |
|---|---|---|---|---|
| L016 | C | C | B | errou |
| L022 | D | D | C | errou |
| L028 | D | A | D | corrigiu |
| L034 | D | C | D | corrigiu |

## Matriz de confusão de api (linhas = gabarito)

| | A | B | C | D | sem tier |
|---|---:|---:|---:|---:|---:|
| **A** | 4 | 1 | 0 | 0 | 0 |
| **B** | 5 | 3 | 0 | 1 | 0 |
| **C** | 0 | 2 | 5 | 1 | 0 |
| **D** | 1 | 0 | 1 | 6 | 0 |
