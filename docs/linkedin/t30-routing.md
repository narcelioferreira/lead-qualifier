# Material para post: roteamento de modelos (T30) [rascunho]

**A pergunta:** preciso do modelo maior em todas as etapas do agente?

**O teste:** o mesmo grafo em duas configurações, nos mesmos 30 leads de teste, contra um gabarito humano. Uma usa só o modelo maior. A outra usa o modelo menor e só escala a extração quando a confiança é baixa ou o score cai na fronteira de um tier.

| | Só o modelo maior | Roteamento |
|---|---:|---:|
| Acurácia | 66,7% | 70,0% |
| Custo equivalente por lead | US$ 0,0028 | US$ 0,0010 |
| Tokens no modelo maior | 100% | 7,1% |
| Leads escalados | — | 5 de 30 |

**O que dá para afirmar:** o roteamento custou cerca de um terço, sem perda de acurácia medida.

**O que não dá para afirmar:** que o roteamento é mais preciso. As duas deram o mesmo tier em 27 dos 30 leads, e a diferença está no ruído (McNemar p = 1,0).

**O erro mais frequente não sumiu com o modelo caro:** leads B promovidos a A acontecem nas duas configurações. Trocar de modelo não resolve esse problema; é preciso olhar a extração e a rubrica.

Gráfico: `t30-custo-acuracia.png`. Números: `evals/reports/04-routing.md`.
