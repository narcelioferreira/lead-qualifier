# LLM-as-judge do próximo passo (T26)

- Judge: `groq-large` · prompt `evals/prompts/next_step_judge.md` (sha256 `8aa2e982fce8`)
- Próximo passo gerado com os prompts `v4` (grafo do MVP + RAG, sem CRM)
- Casos com judge e revisão do autor: **10**
- Concordância na aprovação: **9/10** (aceite: pelo menos 8 de 10, atingido) · kappa de Cohen 0,78

| Critério | Concordância |
|---|---|
| Segue o playbook | 10/10 |
| Fundamentado | 9/10 |
| Específico | 10/10 |
| Seguro | 7/10 |

| Lead | Tier | Judge | Autor | Motivo do judge |
|---|---|---|---|---|
| L024 | A | aprovado | aprovado | A ação segue o playbook do tier A (AE, 24h, ligação + reunião), todas as afirmações são suportadas pelos documentos citados, o passo está customizado para a transportadora Gobor e não contém promessas indevidas ou informações proibidas. |
| L038 | A | reprovado | reprovado | A afirmação de que a solução detecta desvios de combustível em tempo real e permite ações corretivas imediatas não está explicitamente presente nos documentos citados. O restante do conteúdo está alinhado ao playbook e ao caso, mas essa parte carece de suporte documental, violando o critério de grounding. |
| L045 | A | aprovado | aprovado | A ação segue o playbook do tier A (AE, 24h, ligação + reunião), todas as afirmações são suportadas pelos documentos citados, o passo está customizado para o gerente de logística da Destro e não contém promessas indevidas ou informações proibidas. |
| L002 | B | aprovado | aprovado | A ação segue o playbook do tier B (SDR, 48h, e‑mail + ligação). Todos os pontos citados têm suporte nos documentos de case e são apresentados como exemplos, não como dados do lead. O texto está adaptado ao setor de medicamentos e não contém promessas fora do material ou informações de contato. |
| L046 | B | reprovado | reprovado | A afirmação de que a demo "mostrará como a FrotaSense pode replicar esses resultados na Braspress" não está presente nos documentos ou no lead, violando o critério de fundamentação. As demais informações estão alinhadas ao playbook, são específicas ao lead e não apresentam riscos de segurança. |
| L050 | B | aprovado | aprovado | A ação segue o playbook do tier B (SDR, 48h, e‑mail + ligação). Todos os pontos citados têm suporte nos casos citados e nas métricas apresentadas. O passo está adaptado ao pedido de preço do lead e não contém promessas fora do material disponível. |
| L030 | C | reprovado | reprovado | A ação segue o playbook (Marketing, e‑mail de nutrição, sem SLA) e está citada, mas não foi personalizada ao contexto da Distribuidora Rio Guamá (setor de alimentos, 6 veículos, região), sendo genérica para qualquer lead, o que viola o critério de especificidade. |
| L031 | C | aprovado | reprovado | A ação segue o playbook do tier C (Marketing, sem SLA, e‑mail), todas as afirmações são sustentadas pelos documentos citados, o conteúdo está adaptado ao cliente do agronegócio e não contém promessas fora dos casos ou informações proibidas. |
| L035 | D | aprovado | aprovado | A ação segue exatamente o playbook D para concorrentes, está fundamentada no documento citado, o encaminhamento padrão é adequado ao lead e não contém promessas ou informações inseguras. |
| L027 | D | aprovado | aprovado | A ação segue exatamente o que o playbook do tier D indica para estudantes/pesquisa acadêmica, citando o documento correto. Todas as informações usadas estão presentes no lead ou no playbook, sem acrescentar dados externos. O texto está adaptado ao caso da USP e não contém promessas ou informações proibidas. |

Discordâncias: L031.
