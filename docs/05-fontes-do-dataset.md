# 05 · Fontes e protocolo de montagem do dataset de avaliação

## Princípios
1. **Empresas reais e públicas, leads fictícios.** Os nomes e domínios de empresa vêm de fontes públicas. Cargo, mensagem e e-mail são inventados.
2. **Nenhum dado pessoal real.** Não usamos nomes de pessoas nem sócios da base CNPJ. Os e-mails seguem o formato `lead-NNN@example.com`.
3. **Reprodutibilidade.** As evidências coletadas (busca/site) ficam em cache, porque sites mudam com o tempo.

## Fontes de empresas
| Fonte | O que oferece | Uso no dataset |
|---|---|---|
| **Dados abertos do CNPJ (Receita Federal)**: `dadosabertos.rfb.gov.br/CNPJ/dados_abertos_cnpj/` | Razão social, nome fantasia, CNAE, UF/município, porte (ME/EPP/Demais), situação cadastral. Arquivos mensais, ~8 GB compactados | Sortear empresas por CNAE (alvo, adjacente e fora) e região. Fonte da "verdade" de setor |
| **BrasilAPI**: `brasilapi.com.br/api/cnpj/v1/{cnpj}` | Consulta pontual de CNPJ, gratuita, sem baixar a base inteira | Conferir CNAE e situação das empresas escolhidas |
| **ANTT, RNTRC**: `dados.antt.gov.br` (conjunto "rntrc") | Lista de transportadores registrados (razão social, nº RNTRC, situação), CSV com licença CC-BY | Encontrar transportadoras ativas (setor alvo). Conferir a data da última atualização |
| **Rankings setoriais públicos** (ex.: listas de maiores transportadoras e de maiores empresas por setor) | Empresas conhecidas de porte médio/grande | Casos de enterprise (1000+) e empresas reconhecíveis |
| **Sites oficiais das empresas** | Porte declarado, frota, unidades | Base do rótulo humano (o mesmo tipo de evidência que o agente usará) |

> Por que não usar datasets prontos de lead scoring (ex.: o "Lead Scoring" do Kaggle)? Eles são B2C (educação), não têm empresa, cargo nem mensagem, e não se encaixam em qualificação B2B por ICP.

## Composição (50 leads)
| Grupo | Qtde | Como montar |
|---|---|---|
| Esperado **A** | ~12 | Transportadoras/distribuidoras de 50–999 funcionários, no Sul/Sudeste/CO, cargo decisor, mensagem com dor ou pedido de proposta |
| Esperado **B** | ~14 | Setor adjacente com bom cargo, **ou** setor alvo com intenção fraca, **ou** enterprise 1000+ |
| Esperado **C** | ~12 | Frotas pequenas (<50), cargos sem papel, regiões de menor encaixe, curiosidade genérica |
| Esperado **D** | ~12 | Fora do setor, concorrentes (empresas de telemetria), fornecedores vendendo, estudantes, PF, e **~8 tentativas de injeção/spam** distribuídas |

**Casos difíceis (incluir pelo menos 8):** empresa ideal com cargo de estagiário, diretor de empresa fora do setor, empresa com nome ambíguo ou homônimo, site sem informação de porte, grupo empresarial com várias razões sociais, mensagem em inglês, injeção escondida no meio de uma mensagem legítima e lead A disfarçado em mensagem curta.

## Como escrever cargo e mensagem
- Escreva à mão a partir de templates por sinal de intenção (seção 3.5 do contexto), variando tom, tamanho e erros de digitação.
- Se usar um LLM para gerar variações, **revise todas** e use um modelo diferente do modelo do agente. Registre isso no README para evitar o viés "o modelo corrige o próprio texto".

## Formato (`evals/dataset.jsonl`)
```json
{"id": "L001", "split": "dev", "expected_group": "B", "company_name": "…", "company_domain": "…",
 "contact_role": "Diretor de Operações", "contact_email": "lead-001@example.com", "message": "…",
 "source": "site_form", "tags": ["hard_case:ambiguous_name"]}
```
- `expected_group` é o grupo-alvo usado para **montar e estratificar** o dataset (tabela acima). Ele **não** é o rótulo: o tier verdadeiro é definido pela rotulagem humana (T09) e pode divergir dele.
- `tags`: `hard_case:<tipo>` para casos difíceis e `attack:injection` / `attack:spam` para tentativas de manipulação.
- O loader `evals/dataset.py` valida cada linha (`extra="forbid"`) e monta o `LeadInput` só com os campos do lead (`DatasetItem.to_lead_input()`). Assim, `id`, `split`, `expected_group` e `tags` nunca chegam ao agente.

Os rótulos ficam separados em `evals/labels.jsonl` (T09), para que o agente nunca os veja.

## Como o dataset foi montado (T08)
- **Empresas:** escolhidas a partir de rankings setoriais e do conhecimento público do setor. O domínio de cada empresa foi conferido em 20/10/2026 pelo título da home (o site existe e pertence à empresa). Exceções intencionais:
  - `tombini.com.br` é de uma fabricante de móveis, mas o lead se apresenta como frota de entregas (caso de homônimo);
  - 4 leads sem domínio (spam, pessoa física e um caso `hard_case:no_domain`);
  - 2 nomes de spam (`SEO Top Rank`, `asdasd`) não são empresas reais, de propósito.
- **Porte, CNAE e região** não foram fixados no dataset: são levantados pelo anotador na T09 a partir de evidências públicas, como o agente fará. Por isso o grupo-alvo é uma hipótese de montagem.
- **Lacuna conhecida:** não há empresas comprovadamente pequenas (< 50 funcionários) com site verificável. O grupo C foi montado sobretudo por papel sem decisão (estagiário, RH, comercial, jurídico) e intenção fraca. Se a T09 mostrar falta de frotas pequenas, trocar alguns leads do C por transportadoras pequenas do RNTRC.
- **Mensagens e cargos:** escritos pelo Claude (Anthropic), com revisão do autor antes da rotulagem (T09). O agente usa modelos da OpenAI, então quem escreveu o texto não é o modelo avaliado.
- **Dados pessoais:** nenhum nome de pessoa; e-mails `lead-NNN@example.com`; há teste que barra outros e-mails, telefone e CPF nas mensagens.

## Divisão
20 leads de **dev** (para ajustar prompts) e 30 de **teste**, congelados e estratificados por tier esperado. A divisão é feita **antes** de rodar o agente.

## Rotulagem humana (T09)
Feita pelo autor (e, se possível, por um segundo anotador independente), usando só a rubrica de `02-ontologia-icp.md` (seção 5) e evidências públicas. O código apenas valida e consolida.

```bash
# 1. Planilha sem grupo-alvo nem tags (texto já sanitizado, igual ao que o agente recebe)
uv run python scripts/inter_annotator.py sheet --out evals/annotations/planilha-ana.csv
# 2. Preencher tier (A–D), uncertain (x/sim ou vazio) e rationale; depois importar
uv run python scripts/inter_annotator.py import evals/annotations/planilha-ana.csv --annotator ana
# 3. Com dois anotadores: kappa, matriz de confusão e divergências
uv run python scripts/inter_annotator.py compare evals/annotations/ana.jsonl evals/annotations/bia.jsonl
# 4. Discutir as divergências, registrar em resolucoes.jsonl ({"id", "tier", "rationale"}) e consolidar
uv run python scripts/inter_annotator.py merge evals/annotations/ana.jsonl evals/annotations/bia.jsonl \
    --resolutions evals/annotations/resolucoes.jsonl
```
- Cada anotador preenche sua planilha **sem ver** a do outro nem o `dataset.jsonl` (que tem o `expected_group`).
- O relatório vai para `evals/reports/00-concordancia-humana.md`. A métrica principal é o **kappa ponderado linear**, porque os tiers são ordinais.
- O `merge` nunca decide uma divergência sozinho: sem resolução registrada, ele falha. Com um único anotador, o rótulo dele vira o final (`resolution = single_annotator`) e o kappa humano não é calculado.
- Os arquivos `annotations/<anotador>.jsonl`, as resoluções e o relatório são versionados. A planilha CSV é derivada e fica fora do git.
