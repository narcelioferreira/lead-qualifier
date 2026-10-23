#!/usr/bin/env bash
# Smoke de ponta a ponta (T22): sobe o sistema completo, qualifica um lead do split dev pela
# API e confere o tier no resultado e o registro no HubSpot.
#
# Uso (na raiz do repositório, com o .env preenchido):
#   scripts/smoke_e2e.sh            # sobe/reconstrói tudo e testa
#   SMOKE_NO_BUILD=1 scripts/smoke_e2e.sh   # reaproveita as imagens já construídas
#
# Gasta ~4,5K tokens da Groq e até 1 busca da Tavily (com cache). Grava no HubSpot (empresa,
# contato e uma Note), como o sistema real. Nenhum segredo é impresso nem passado na linha de
# comando: os headers vão para o curl por um descritor de arquivo.
set -euo pipefail

cd "$(dirname "$0")/.."
API_URL="http://127.0.0.1:${API_PORT:-8000}"
HUBSPOT_URL="https://api.hubapi.com"
WAIT_UP_S=300
WAIT_RUN_S=180

fail() { echo "FALHOU: $*" >&2; docker compose logs --tail 40 api tools-mcp >&2 || true; exit 1; }

# Lê uma variável do .env sem executá-lo (`source` rodaria qualquer comando do arquivo).
env_get() {
  local value
  value="$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2-)" || true
  value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

json_get() { python3 -c 'import json,sys; d=json.load(sys.stdin)
for k in sys.argv[1].split("."): d=d.get(k) if isinstance(d, dict) else None
print("" if d is None else d)' "$1"; }

[[ -f .env ]] || fail ".env não encontrado (copie o .env.example e preencha)"
API_KEY="$(env_get API_KEY)"
HUBSPOT_TOKEN="$(env_get HUBSPOT_TOKEN)"
WRITE_CRM="$(env_get API_WRITE_CRM)"
[[ -n "$API_KEY" ]] || fail "API_KEY vazia no .env"

echo "1/5 subindo o sistema (postgres → migrate → tools-mcp → api)"
if [[ "${SMOKE_NO_BUILD:-0}" == "1" ]]; then
  docker compose up -d api
else
  docker compose up -d --build api
fi

echo "2/5 aguardando /health (até ${WAIT_UP_S}s)"
deadline=$((SECONDS + WAIT_UP_S))
until curl -fsS "$API_URL/health" >/dev/null 2>&1; do
  ((SECONDS < deadline)) || fail "/health não ficou ok"
  sleep 3
done
curl -fsS "$API_URL/health"; echo

echo "3/5 sem chave → 401"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/v1/leads/qualify" \
  -H 'Content-Type: application/json' -d '{}')"
[[ "$code" == "401" ]] || fail "esperado 401 sem chave, veio $code"

echo "4/5 qualificando L024 (Gobor Transportes, split dev)"
lead='{"company_name": "Gobor Transportes", "company_domain": "gobor.com.br",
  "contact_role": "Diretor de Operações", "contact_email": "lead-024@example.com",
  "message": "Temos 85 caminhões em SP e MG e queremos uma proposta de telemetria.",
  "source": "demo_request"}'
accepted="$(curl -fsS -X POST "$API_URL/v1/leads/qualify" -H 'Content-Type: application/json' \
  -H @<(printf 'X-API-Key: %s\n' "$API_KEY") -d "$lead")" || fail "POST recusado"
run_id="$(json_get run_id <<<"$accepted")"
[[ -n "$run_id" ]] || fail "resposta sem run_id: $accepted"
echo "   run_id=$run_id"

deadline=$((SECONDS + WAIT_RUN_S))
while :; do
  run="$(curl -fsS "$API_URL/v1/runs/$run_id" -H @<(printf 'X-API-Key: %s\n' "$API_KEY"))"
  status="$(json_get status <<<"$run")"
  [[ "$status" != "running" ]] && break
  ((SECONDS < deadline)) || fail "execução ainda running após ${WAIT_RUN_S}s"
  sleep 2
done
tier="$(json_get tier <<<"$run")"
echo "   status=$status tier=$tier score=$(json_get score <<<"$run") custo=US\$$(json_get cost_usd <<<"$run")"
[[ "$status" == "completed" || "$status" == "needs_review" ]] || \
  fail "status $status: $(json_get errors <<<"$run")"
[[ "$tier" =~ ^[ABCD]$ ]] || fail "tier inválido: $tier"

echo "5/5 conferindo o registro no HubSpot"
if [[ "$WRITE_CRM" == "false" ]]; then
  echo "   API_WRITE_CRM=false: CRM desligado, conferência pulada"
else
  company_id="$(json_get crm_ids.company_id <<<"$run")"
  note_id="$(json_get crm_ids.note_id <<<"$run")"
  [[ -n "$company_id" && -n "$note_id" ]] || fail "sem ids do CRM: $(json_get errors <<<"$run")"
  [[ -n "$HUBSPOT_TOKEN" ]] || fail "HUBSPOT_TOKEN vazio no .env (necessário para conferir)"
  company="$(curl -fsS "$HUBSPOT_URL/crm/v3/objects/companies/$company_id?properties=ai_run_id,ai_fit_tier" \
    -H @<(printf 'Authorization: Bearer %s\n' "$HUBSPOT_TOKEN"))" || fail "empresa $company_id não encontrada"
  [[ "$(json_get properties.ai_run_id <<<"$company")" == "$run_id" ]] || fail "ai_run_id não confere"
  [[ "$(json_get properties.ai_fit_tier <<<"$company")" == "$tier" ]] || fail "ai_fit_tier não confere"
  echo "   empresa $company_id com ai_run_id e ai_fit_tier=$tier · Note $note_id"
fi

echo "OK: smoke de ponta a ponta passou"
