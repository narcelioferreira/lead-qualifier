# Material para post: sistema completo em Docker e uma demo que roda sem chave (T22)

- `docker compose up` sobe o sistema inteiro: Postgres, migrations, servidor MCP de ferramentas, API e Ollama. A API só sobe depois que as migrations terminam e o servidor MCP está saudável.
- **Cada container só conhece os segredos que usa.** A API tem a chave da Groq, mas não a da Tavily nem a do HubSpot, que ficam só no container de ferramentas. Um teste quebra se alguém passar o `.env` inteiro para um serviço.
- **Como mostrar um agente que depende de 3 APIs pagas sem entregar as chaves?** Gravei uma vez as respostas reais da Groq, da Tavily e dos sites para 5 leads e reproduzo essas respostas no GitHub Actions. A API, o grafo, a rubrica, as regras e o detector de injeção rodam de verdade; só as chamadas externas vêm da gravação.
- Para provar que a demo é mesmo offline, um *audit hook* do Python bloqueia qualquer conexão fora da própria máquina. Se algum código tentar sair para a internet, a demo quebra.
- A demo não esconde erro: num dos 5 leads o agente discordou do rótulo humano (B → C), e o relatório mostra isso.
- 📸 GIF: `docker compose up` → `scripts/smoke_e2e.sh` → resultado no `/docs` e a Note no HubSpot (gravado pelo autor). Print do Job Summary da execução "Demo offline" no Actions.
- Execução da demo no Actions (16 s, sem secrets): https://github.com/narcelioferreira/lead-qualifier/actions/runs/40022574667
