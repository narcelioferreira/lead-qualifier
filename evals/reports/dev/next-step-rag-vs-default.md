# Próximo passo: com RAG × passo padrão do tier (T27)

- Judge: `groq-large`, a mesma rubrica da T26; aprovação calculada pelo código
- Com RAG: os casos da T26 (`next-step-judge-dev.jsonl`, prompts de next_step iguais na `v5`)
- Padrão: ação, responsável e prazo do tier (`TIER_PLANS`), citando o playbook
- Casos nos dois braços: **8** (tier D fora: usa o padrão nos dois)

| Critério | Com RAG | Padrão |
|---|---|---|
| Segue o playbook | 8/8 | 7/8 |
| Fundamentado | 6/8 | 4/8 |
| Específico | 7/8 | 2/8 |
| Seguro | 8/8 | 8/8 |
| **Aprovado** | 5/8 | 2/8 |

| Lead | Tier | Com RAG | Padrão | Motivo do judge (padrão) |
|---|---|---|---|---|
| L024 | A | aprovado | aprovado | A ação segue o playbook do tier A (AE, ligação, convite para reunião de 45 min, SLA 24 h), todas as afirmações estão suportadas pelos documentos citados e não há promessas fora do permitido, e o convite inclui simulação de economia baseada no porte do cliente, mostrando personalização. |
| L038 | A | reprovado | aprovado | A ação segue o playbook (AE, ligação, convite para reunião de 45 min, SLA 24 h). Todas as afirmações estão suportadas pelos documentos (playbook e cases) e não há números ou promessas não comprovadas. O passo foi adaptado ao problema de aumento de diesel do lead, usando um case similar, e não contém ofertas ou informações inseguras. |
| L045 | A | aprovado | reprovado | A ação segue o playbook (AE, ligação, reunião de 45 min e SLA de 24 h), mas a menção à ‘simulação de economia’ não tem suporte nos documentos citados, violando o critério de grounding. Além disso, o passo não menciona detalhes do lead (contrato que vence em março, necessidade de comparar alternativas), parecendo genérico para qualquer lead do tier A. O restante está seguro. |
| L002 | B | aprovado | reprovado | A ação inclui "cadência de 10 dias úteis", informação que não consta nos documentos citados, violando o critério de grounding. Além disso, o passo não traz adaptações ao setor de distribuidora de medicamentos ou ao cargo de coordenador de frota, sendo genérico e falhando no critério de especificidade. |
| L046 | B | reprovado | reprovado | A ação adiciona uma cadência de 10 dias úteis, que não consta no playbook do tier B (que exige contato em até 48h). Também inclui detalhes de confirmação de decisor, frota e dor sem suporte nas citações fornecidas. O texto é genérico e não traz adaptações ao setor ou ao cargo do lead, falhando nos critérios de especificidade. |
| L050 | B | aprovado | reprovado | A ação cita uma cadência de 10 dias úteis, informação que não consta nos documentos, violando o critério de grounding; além disso, não inclui detalhes do lead (empresa ou pedido de tabela), sendo genérica e não específica. O responsável, canal e SLA estão corretos e não há violação de segurança. |
| L030 | C | reprovado | reprovado | A ação segue o playbook e está fundamentada nas citações, mas o conteúdo proposto é genérico e não traz elementos específicos ao setor de alimentos, porte ou intenção do lead, portanto não atende ao critério de especificidade. |
| L031 | C | aprovado | reprovado | A ação segue o playbook e está fundamentada nas citações, mas o conteúdo proposto é genérico e não traz personalização para a SLC Agrícola (setor agrícola, analista de compras), violando o critério de especificidade. |
