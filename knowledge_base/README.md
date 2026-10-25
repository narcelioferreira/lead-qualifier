# Base de conhecimento da FrotaSense (fictícia)

> **Aviso:** a FrotaSense, os clientes dos cases, os números e os preços são **fictícios**, criados para fins acadêmicos. Nenhuma empresa do dataset de avaliação aparece aqui.

Documentos internos usados pelo RAG agêntico: o `suggest_next_step` (T26) recupera o playbook do tier e os cases do setor e cita o `doc_id`.

| Tipo (`doc_type`) | O que contém | Documentos |
|---|---|---|
| `playbook` | Ação, canal, prazo e roteiro para cada tier | 4 (A, B, C, D) |
| `case` | Resultado de um cliente fictício de um segmento | 8 |
| `objection` | Objeção comum e como responder | 5 |
| `product` | Módulos, preços, implantação e integrações | 4 |

## Front-matter

```yaml
---
doc_id: case-transportadora-serra-azul   # igual ao nome do arquivo
title: Case Transportadora Serra Azul
doc_type: case                           # playbook | case | objection | product
tiers: [A, B]                            # vazio = todos os tiers
segments: [transporte_cargas]            # vazio = todos os segmentos
version: 1
updated: 2026-10-24
---
```

Regras (validadas por `app/knowledge_base.py` e `tests/unit/test_kb.py`):
- playbook tem exatamente um tier; case tem exatamente um segmento e não vale para o tier D;
- o setor da ontologia (`target`, `adjacent`) sai do CNAE do segmento, pela mesma taxonomia que classifica o lead;
- o corpo tem seções `## ` (a ingestão da T24 divide por seção);
- o texto não pode ter padrões de injeção, caracteres invisíveis, HTML, links nem dados pessoais. A base vai para o prompt como contexto confiável, então um documento envenenado seria uma injeção com a autoridade da empresa.
