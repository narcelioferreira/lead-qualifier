# 03 · Contratos de entrada e saída

Código: `app/schemas.py` (contratos) e `app/config.py` (configuração).

## LeadInput (entrada da API)
| Campo | Tipo | Regras |
|---|---|---|
| `company_name` | str | 2–200 caracteres, sem caracteres de controle/invisíveis |
| `company_domain` | str \| null | Normalizado (`https://www.X.com.br/a` → `x.com.br`). **Rejeita** IP, localhost, `.local/.internal/...`, porta e credenciais (proteção SSRF) |
| `contact_role` | str | 2–120 caracteres |
| `contact_email` | email \| null | Validado (`email-validator`) |
| `message` | str | Até 4.000 caracteres, sanitizada (remove Cc/Cf, como zero-width e override bidi) e normalizada em NFKC |
| `source` | enum | `site_form`, `demo_request`, `event`, `content`, `api` |

Campos extras são **rejeitados** (`extra="forbid"`). Isso impede, por exemplo, que um cliente envie `"tier": "A"` junto do lead. O objeto é imutável.

> Todo texto do `LeadInput` é **dado não confiável**. A sanitização reduz a superfície de ataque, mas não substitui o guardrail (T28) nem a delimitação nos prompts.

## QualificationResult (saída)
| Campo | Descrição |
|---|---|
| `run_id` | ID da execução (auditoria) |
| `tier` | A, B, C ou D |
| `score` | 0–100 (rubrica, `02-ontologia-icp.md`) |
| `is_borderline` | Score a até 5 pontos de um limite de tier |
| `confidence` | 0–1 |
| `needs_human_review` | Regra de incerteza da ontologia |
| `disqualifiers` / `caps_applied` | Regras K* e C* disparadas |
| `criteria[]` | `CriterionScore`: critério, valor ontológico, pontos, máximo e evidências |
| `next_step` | Ação, responsável, SLA, argumentos e citações da base de conhecimento |
| `rationale` | Justificativa em linguagem natural (até 4.000 caracteres) |
| `prompt_version`, `cost_usd` | Rastreabilidade e custo |

## Evidence
`source_type` (`web_search`, `company_site`, `knowledge_base`, `lead_message`), `source_url`, `snippet` (até 1.000 caracteres, sanitizado) e `retrieved_at`.

## Settings (variáveis de ambiente)
| Variável | Obrigatória | Observação |
|---|---|---|
| `API_KEY` | ✔ | Mínimo de 32 caracteres; o valor de exemplo do `.env.example` é rejeitado |
| `DATABASE_URL` | ✔ | `SecretStr` (contém senha) |
| `OPENAI_API_KEY`, `TAVILY_API_KEY`, `HUBSPOT_TOKEN`, `LANGSMITH_API_KEY` | — | `SecretStr`; obrigatórias apenas nas tasks que as usam |
| `APP_ENV` | — | `dev`, `test` ou `prod` |
| `MAX_MESSAGE_CHARS` | — | 100–20.000 (padrão 4.000) |

Todos os segredos usam `SecretStr` e não aparecem em `repr`, logs nem tracebacks (há teste para isso).
