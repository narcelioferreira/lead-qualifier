# Material para post: RAG agêntico vale o custo? (T27)

Ablação no split **test** (30 leads de empresas reais, rodada única), comparando o MVP com a mesma
configuração mais o **RAG agêntico**: o modelo aponta o que falta saber da empresa e propõe a
próxima busca, e o **código** decide quando parar (até 3 iterações). O próximo passo comercial
passa a ser escrito a partir de playbooks e cases da base de conhecimento, com citação conferida.

| | MVP | MVP + RAG agêntico |
|---|---:|---:|
| Acurácia (IC 95%) | 60,0% (43–77%) | 66,7% (50–83%) |
| Kappa ponderado (IC 95%) | 0,560 (0,31–0,77) | 0,662 (0,45–0,84) |
| Ataques desqualificados | 3/4 | 3/4 |
| Tokens por lead | 3,7K | 8,0K (2,2×) |
| Latência p50 | 4,6 s | 11,9 s |
| Próximo passo aprovado pelo judge (dev, A/B/C) | 2/8 (passo padrão) | 5/8 |

- **No tier, o ganho não se distingue do ruído.** +6,7 p.p. no test, −5 p.p. no dev; McNemar
  p = 0,69. Com 30 leads, publicar o IC é mais honesto do que publicar o número maior.
- **A auditoria de cada lead mostra de onde vem cada mudança.** A pesquisa corrigiu 2 transportadoras
  grandes ao achar o porte real (o código aplicou o teto). E piorou um homônimo: buscou o porte num
  site de **outra empresa** com nome parecido. O controle que falta é conferir o domínio da fonte, e
  ele é do código, não do prompt.
- **Onde o RAG paga:** no próximo passo. O texto deixa de ser genérico e passa a citar o playbook e um
  case parecido, conferidos pelo código. O risco novo é atribuir o número de um case ao lead errado.
- **Custo:** 2,2× os tokens. No plano gratuito da Groq, o test levou dois dias de cota, retomado de
  onde parou.
