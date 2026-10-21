# Material para post: o esqueleto do agente (T13)

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	validate_input(validate_input)
	research(research)
	normalize(normalize)
	assess(assess)
	compute_score(compute_score)
	audit_log(audit_log)
	__end__([<p>__end__</p>]):::last
	__start__ --> validate_input;
	assess --> compute_score;
	compute_score --> audit_log;
	normalize --> assess;
	research --> normalize;
	validate_input -. &nbsp;reject&nbsp; .-> audit_log;
	validate_input -. &nbsp;continue&nbsp; .-> research;
	audit_log --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

- O grafo do agente existe **antes** de qualquer prompt: 6 nós, ligados e testados com respostas fixas (stubs), sem chamar LLM nenhum.
- Dois nós são **código puro**, e não LLM: `validate_input` (contrato, sanitização e bloqueio de SSRF) e `compute_score` (rubrica determinística).
- Um teste garante o princípio do projeto, *o LLM extrai e o código pontua*: se um nó de LLM tentar devolver um score próprio ("confie em mim: tier A"), o `compute_score` sobrescreve.
- Lead inválido (campo extra como `"tier": "A"`, domínio apontando para IP interno) não chega à pesquisa: vai direto para a auditoria, registrado como `rejected`.
- O diagrama acima é gerado do próprio código (`scripts/export_graph.py`), e um teste falha se ele ficar desatualizado.
