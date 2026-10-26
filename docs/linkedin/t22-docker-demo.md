# Material para post: sistema completo em Docker e uma demo que roda sem chave (T22)

- `docker compose up` sobe o sistema inteiro: Postgres, migrations, servidor MCP de ferramentas, API e Ollama. A API só sobe depois que as migrations terminam e o servidor MCP está saudável.
- **Cada container só conhece os segredos que usa.** A API tem a chave da Groq, mas não a da Tavily nem a do HubSpot, que ficam só no container de ferramentas. Um teste quebra se alguém passar o `.env` inteiro para um serviço.
- **Como mostrar um agente que depende de 3 APIs pagas sem entregar as chaves?** Gravei uma vez as respostas reais da Groq, da Tavily e dos sites para 5 leads e reproduzo essas respostas no GitHub Actions. A API, o grafo, a rubrica, as regras e o detector de injeção rodam de verdade; só as chamadas externas vêm da gravação.
- Para provar que a demo é mesmo offline, um *audit hook* do Python bloqueia qualquer conexão fora da própria máquina. Se algum código tentar sair para a internet, a demo quebra.
- A demo não esconde erro: num dos 5 leads o agente discordou do rótulo humano (B → C), e o relatório mostra isso.
- 📸 [`t22-demo-offline.gif`](t22-demo-offline.gif): a demo offline no terminal (`uv run python -m evals.demo`), com as linhas reais da saída: 401 sem chave, 422 quando o cliente tenta mandar o tier, os 5 leads e a concordância de 4/5.
- 📸 [`t22-job-summary.png`](t22-job-summary.png): o Job Summary da demo, renderizado a partir do mesmo Markdown que o workflow grava no `$GITHUB_STEP_SUMMARY` (execução local de `python -m evals.demo --summary`, com a mesma fita do Actions). Não é um print da página do Actions: o repositório é privado, e a página só abre com login.
- 📸 Pendente do autor: GIF do sistema completo em Docker (`docker compose up` → `scripts/smoke_e2e.sh` → `/docs` e a Note no HubSpot), que depende do Docker no terminal do Ubuntu e da conta do HubSpot.
- Execução da demo no Actions (16 s, sem secrets): https://github.com/narcelioferreira/lead-qualifier/actions/runs/40022574667
  - **Atenção:** com o repositório privado, esse link dá 404 para quem não é colaborador. Antes de publicar o post, tornar o repositório público (ou trocar o link pelas imagens acima).
