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
{"id": "L001", "split": "dev", "company_name": "…", "company_domain": "…", "contact_role": "Diretor de Operações",
 "contact_email": "lead-001@example.com", "message": "…", "source": "site_form",
 "tags": ["hard_case:ambiguous_name"]}
```
Os rótulos ficam separados em `evals/labels.jsonl` (T09), para que o agente nunca os veja.

## Divisão
20 leads de **dev** (para ajustar prompts) e 30 de **teste**, congelados e estratificados por tier esperado. A divisão é feita **antes** de rodar o agente.
