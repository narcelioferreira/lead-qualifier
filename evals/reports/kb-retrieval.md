# Busca na base de conhecimento: hit rate

| Modo | Hit rate@k | Acertos | MRR |
|---|---:|---:|---:|
| com filtro | 100% (k=3) | 10/10 | 1.00 |
| sem filtro | 100% (k=3) | 10/10 | 0.77 |

## Com filtro

| Pergunta | Esperado | Posição | Recuperados |
|---|---|---:|---|
| Q01 | `playbook-tier-a` | 1 | `playbook-tier-a` |
| Q02 | `playbook-tier-b` | 1 | `playbook-tier-b` |
| Q03 | `playbook-tier-d` | 1 | `playbook-tier-d` |
| Q04 | `case-transportadora-serra-azul` | 1 | `case-transportadora-serra-azul`, `case-rodo-cerrado-cargas` |
| Q05 | `case-distribuidora-vale-verde` | 1 | `case-distribuidora-vale-verde`, `case-atacadista-litoral-sul` |
| Q06 | `case-agro-tres-rios` | 1 | `case-agro-tres-rios`, `case-armazens-ponte-alta`, `case-construtora-horizonte` |
| Q07 | `objecao-preco` | 1 | `objecao-preco`, `objecao-ja-tenho-rastreador`, `objecao-tempo-implantacao` |
| Q08 | `objecao-resistencia-motoristas` | 1 | `objecao-resistencia-motoristas`, `objecao-preco`, `objecao-ja-tenho-rastreador` |
| Q09 | `produto-precos-implantacao` | 1 | `produto-precos-implantacao`, `produto-visao-geral`, `produto-modulos` |
| Q10 | `produto-integracoes-seguranca` | 1 | `produto-integracoes-seguranca`, `produto-precos-implantacao`, `produto-visao-geral` |

## Sem filtro

| Pergunta | Esperado | Posição | Recuperados |
|---|---|---:|---|
| Q01 | `playbook-tier-a` | 3 | `playbook-tier-b`, `playbook-tier-c`, `playbook-tier-a` |
| Q02 | `playbook-tier-b` | 1 | `playbook-tier-b`, `playbook-tier-c`, `playbook-tier-d` |
| Q03 | `playbook-tier-d` | 1 | `playbook-tier-d`, `objecao-preco`, `playbook-tier-c` |
| Q04 | `case-transportadora-serra-azul` | 1 | `case-transportadora-serra-azul`, `produto-modulos`, `objecao-preco` |
| Q05 | `case-distribuidora-vale-verde` | 1 | `case-distribuidora-vale-verde`, `playbook-tier-d`, `objecao-preco` |
| Q06 | `case-agro-tres-rios` | 1 | `case-agro-tres-rios`, `case-rodo-cerrado-cargas`, `objecao-preco` |
| Q07 | `objecao-preco` | 2 | `case-rodo-cerrado-cargas`, `objecao-preco`, `playbook-tier-d` |
| Q08 | `objecao-resistencia-motoristas` | 1 | `objecao-resistencia-motoristas`, `produto-visao-geral`, `case-transportadora-serra-azul` |
| Q09 | `produto-precos-implantacao` | 3 | `objecao-tempo-implantacao`, `objecao-integracao-ti`, `produto-precos-implantacao` |
| Q10 | `produto-integracoes-seguranca` | 2 | `objecao-integracao-ti`, `produto-integracoes-seguranca`, `playbook-tier-b` |
