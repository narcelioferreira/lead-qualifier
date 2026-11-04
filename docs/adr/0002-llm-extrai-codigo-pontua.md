# ADR 0002: o LLM extrai e justifica; o código pontua

- **Status:** aceito (2026-10-20, T02 e T07)
- **Evidência:** `app/ontology/scoring.py`, `app/ontology/rubric.yaml`,
  `docs/02-ontologia-icp.md`, `evals/reports/01-baseline.md`, `evals/reports/02-mvp.md`

## Contexto

Um tier decide quem o vendedor atende primeiro, então precisa ser explicável e reproduzível. Se o
LLM desse a nota, ela mudaria entre execuções e entre versões do modelo, ninguém conseguiria testar
a regra de negócio, e um texto no formulário poderia pedir a nota que quisesse.

## Decisão

1. O LLM devolve só **fatos e valores da ontologia** (`Extraction`, `app/ontology/models.py`), com
   `extra="forbid"`. O schema não tem campo de score nem de tier.
2. O **score, as regras K1–K7, os tetos C1–C4 e o tier** saem de `scoring.py` + `rubric.yaml`, sem
   LLM. A mesma rubrica serve aos prompts e ao guia de rotulagem humana.
3. O código também converte fatos em conceitos: setor pelo CNAE, região pela UF e porte pelos
   funcionários. Um CNAE que não aparece em nenhuma evidência é descartado.
4. A confiança é calculada a partir das certezas, e não autodeclarada pelo LLM.
5. O LLM só redige a justificativa, que não muda o score.

## Consequências

- **Regra de negócio com teste unitário:** os exemplos E1–E8 da ontologia rodam sem LLM.
- **Dano de uma injeção limitado:** na T14, a mensagem da L005 pedia tier A com score 100, e o mini
  não marcou a flag. O código só calculou os critérios, e o lead saiu B pelo teto C1, em vez de A.
- **Comparável no tempo:** trocar modelo ou prompt muda a extração, e a auditoria mostra qual
  critério mudou.
- **Medição (rodada única no test, 30 leads):** baseline com prompt único 53,3% / κ 0,475 × MVP
  60,0% / κ 0,560. Limites: a amostra é pequena (IC 95% do MVP de 43,3% a 76,7%), e o baseline teve
  3 falhas de schema da Groq contadas como erro. O número não prova o ganho sozinho; o principal
  argumento desta decisão é a auditabilidade.
- **O código não corrige fato errado.** Se o LLM for enganado sobre os fatos, a nota sai errada de
  forma determinística. Por isso a evidência citada, os tetos e a revisão humana continuam
  necessários. Um caso conhecido: o CNAE que o próprio lead escreve na mensagem conta como evidência
  (`tests/security/`).

## Alternativas descartadas

- **O LLM dá a nota, com rubrica no prompt:** é a configuração `baseline`, mantida como referência
  da avaliação. A nota não é testável nem auditável por critério.
- **Modelo treinado com os rótulos:** 50 leads não bastam, e a explicação por critério se perderia.
