# ADR 0004: MCP como fronteira das integrações externas

- **Status:** aceito (2026-10-23, T19 e T20)
- **Evidência:** `tools_mcp/server.py`, `app/mcp_client.py`, `tests/unit/test_mcp_server.py`,
  `tests/graph/test_crm.py`

## Contexto

O agente lê texto não confiável e, com a mesma execução, escreve no CRM. Se o processo que fala com
o LLM também guardasse as chaves do HubSpot e da Tavily, uma falha nele exporia essas chaves. A
leitura de sites também é o ponto mais exposto a SSRF.

## Decisão

1. **Busca, site, base de conhecimento e HubSpot ficam no servidor MCP `lead-tools`**, em um
   container próprio (`tools-mcp`), com Streamable HTTP e Bearer token obrigatório.
2. **Segredos separados por container:** o `tools-mcp` não recebe `API_KEY` nem `GROQ_API_KEY`, e a
   API não recebe as chaves da Tavily e do HubSpot. O grafo só conhece a URL e o token do servidor.
3. **Superfície fechada:** 7 tools com schema Pydantic, allowlist de campos do CRM e argumentos
   desconhecidos recusados. Nenhuma tool apaga dados.
4. **Grafo com arestas fixas:** o LLM não recebe as tools. Quem as chama é o código dos nós.
5. **O próprio agente também é um servidor MCP** (`lead-qualifier`, T32), sem tool de revisão
   humana, para o LLM do cliente não aprovar o próprio resultado.

## Consequências

- **Raio de dano menor:** o container de tools roda sem root, com sistema de arquivos só leitura e
  sem capabilities. Controles testados por mutação (T19 e T20).
- **Contrato testável:** os testes de grafo usam o cliente MCP in-process, e a mesma fachada
  (`LeadTools`) serve a produção.
- **Reuso:** qualquer cliente MCP consegue usar as tools, sem código novo no agente.
- **Custos que apareceram:**
  - mais um container para subir, com healthcheck e dependências;
  - o SDK **ignora em silêncio argumentos desconhecidos**: um container desatualizado descartou o
    `run_id` e criou Notes duplicadas no HubSpot (T20). Por isso o servidor passou a recusá-los, e
    um novo código de tool exige reconstruir a imagem;
  - o MCP Inspector no navegador não conecta direto, porque o preflight CORS não leva o token.

## Alternativas descartadas

- **Chamadas diretas de dentro do grafo:** foi a versão da T12. Mais simples, mas as chaves ficam no
  processo do LLM.
- **`langchain-mcp-adapters`:** era o plano. A versão 0.3.2 exige `mcp<2`, incompatível com o
  servidor. Como o LLM não recebe as tools, o adapter não traria ganho, e o grafo usa o cliente
  oficial do SDK.
- **API REST interna própria:** daria a mesma separação, mas sem o protocolo padrão que permite
  reusar as tools em outros clientes. Não foi implementada.
