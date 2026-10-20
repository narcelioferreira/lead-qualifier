# 00 · Rotulagem humana (gabarito da avaliação)

- **Anotador:** autor do projeto (anotador único, `resolution = single_annotator`).
- **Método:** rubrica de `docs/02-ontologia-icp.md` e evidências públicas (mensagem e site). A planilha não mostrava o grupo-alvo nem as tags do dataset.
- **Data:** 2026-10-20

## Distribuição dos rótulos
| Tier | Dev (20) | Teste (30) | Total |
|---|---:|---:|---:|
| A | 5 | 5 | 10 |
| B | 5 | 9 | 14 |
| C | 4 | 8 | 12 |
| D | 6 | 8 | 14 |

Rótulos marcados como incertos: **12 de 50**, na maioria por porte da empresa não evidenciado publicamente.

## Ajustes da rubrica motivados pela rotulagem
1. **Teto C4** (porte 1–49 → máximo B): uma transportadora pequena com dono e dor explícita chegava a A.
2. **Área `unspecified`**: "Diretor" ou "Sócio" sem área explícita passou a ser decisor. Antes, um diretor pedindo proposta para 60 caminhões virava C.

Os dois ajustes foram feitos **antes** de qualquer execução do agente, para não contaminar a avaliação.

## Limitação
Com um único anotador, a **concordância entre humanos (kappa) não foi medida**, então não há um "teto humano" de referência para a concordância do agente. As ferramentas para um segundo anotador estão prontas (`scripts/inter_annotator.py compare`).
