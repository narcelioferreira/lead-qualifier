# ADR 0005: pgvector no lugar de um banco vetorial dedicado

- **Status:** aceito (2026-10-24, T24)
- **Evidência:** `tools_mcp/kb.py`, `app/audit/vector.py`, `evals/kb_eval.py`,
  `evals/reports/kb-retrieval.md`

## Contexto

A base de conhecimento tem 21 documentos fictícios, que viram 96 chunks. O projeto já depende do
Postgres para auditoria, cache e checkpoints. A busca precisa combinar similaridade com filtros por
tipo, tier, setor e segmento.

## Decisão

1. **Guardar os embeddings no Postgres com pgvector**, na tabela `kb_chunks` (migration 0004), com
   `nomic-embed-text:v1.5` no Ollama.
2. **Busca exata por cosseno, sem índice ANN.** Com cerca de 100 chunks, ela é instantânea e tem
   recall de 100%. Um HNSW só compensa com dezenas de milhares de chunks.
3. **Tipo `vector` próprio** (`app/audit/vector.py`, cerca de 40 linhas), sem o pacote `pgvector`:
   uma dependência a menos, e a dimensão e os valores finitos são conferidos antes do envio.
4. **Filtro de metadado junto da busca**, com um resultado por documento.

## Consequências

- **Menos infraestrutura:** nenhum serviço novo no compose. Backup, migrations e permissões são os
  do Postgres.
- **Filtros em SQL:** é o filtro que coloca o documento certo em 1º lugar:

  | Modo | Hit rate@3 | MRR |
  |---|---:|---:|
  | Com filtro (como o agente usa) | 100% (10/10) | 1,00 |
  | Só vetorial | 100% (10/10) | 0,77 |

- **Limite da medição:** são 10 perguntas, escritas junto com os documentos, e
  tendem a usar o vocabulário da base, o que deixa o número otimista. A medida que importa é o
  julgamento do próximo passo (T26 e T27).
- **Escala:** a busca exata fica lenta com uma base muito maior. Nesse caso, o caminho é criar um
  índice HNSW, sem trocar de banco.
- **Acoplamento:** o tipo próprio precisa acompanhar o formato do pgvector.

## Alternativas descartadas

Nenhuma foi medida: com este volume, o desempenho não seria o fator decisivo.

- **Banco vetorial dedicado (Qdrant, Weaviate, Pinecone):** mais um serviço para operar e proteger,
  sem ganho para 96 chunks.
- **Índice em memória (FAISS ou Chroma embarcado):** os dados ficariam fora do Postgres, com filtro
  e persistência à parte.
