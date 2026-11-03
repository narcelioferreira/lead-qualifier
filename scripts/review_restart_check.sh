#!/usr/bin/env bash
# Revisão humana com restart do container (T31): um lead incerto para em `needs_review`, a API
# é reiniciada, a execução continua lá e a decisão humana retoma o grafo do checkpoint.
#
# Uso (na raiz do repositório, com o .env preenchido):
#   scripts/review_restart_check.sh             # reconstrói a imagem da API e testa
#   SMOKE_NO_BUILD=1 scripts/review_restart_check.sh
#
# Usa os leads L042 e L031 do split dev (os dois saem `needs_review` no MVP v2); para no
# primeiro que parar para revisão. Gasta ~4,5K tokens da Groq por lead e grava no HubSpot depois
# da decisão, como o sistema real. Nenhum segredo é impresso nem passado na linha de comando.
set -euo pipefail

cd "$(dirname "$0")/.."
API_URL="http://127.0.0.1:${API_PORT:-8000}"
WAIT_UP_S=300
WAIT_RUN_S=180

fail() { echo "FALHOU: $*" >&2; docker compose logs --tail 40 api >&2 || true; exit 1; }

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

# Só os campos do `LeadInput` (o dataset tem id, rótulo e tags, que o agente nunca vê).
lead_json() { python3 -c 'import json,sys
fields = ("company_name", "company_domain", "contact_role", "contact_email", "message", "source")
for line in open("evals/dataset.jsonl", encoding="utf-8"):
    row = json.loads(line)
    if row["id"] == sys.argv[1]:
        print(json.dumps({k: row[k] for k in fields if row.get(k) is not None}))' "$1"; }

api() { curl -fsS -H @<(printf 'X-API-Key: %s\n' "$API_KEY") "$@"; }

wait_health() {
  local deadline=$((SECONDS + WAIT_UP_S))
  until curl -fsS "$API_URL/health" >/dev/null 2>&1; do
    ((SECONDS < deadline)) || fail "/health não ficou ok"
    sleep 3
  done
}

wait_status() {  # espera sair de `running`
  local deadline=$((SECONDS + WAIT_RUN_S))
  while :; do
    run="$(api "$API_URL/v1/runs/$1")"
    [[ "$(json_get status <<<"$run")" != "running" ]] && return
    ((SECONDS < deadline)) || fail "execução $1 ainda running após ${WAIT_RUN_S}s"
    sleep 2
  done
}

[[ -f .env ]] || fail ".env não encontrado"
API_KEY="$(env_get API_KEY)"
[[ -n "$API_KEY" ]] || fail "API_KEY vazia no .env"
[[ "$(env_get API_HUMAN_REVIEW)" != "false" ]] || fail "API_HUMAN_REVIEW=false no .env"

echo "1/6 subindo o sistema (migrate aplica a 0005)"
if [[ "${SMOKE_NO_BUILD:-0}" == "1" ]]; then docker compose up -d api; else docker compose up -d --build api; fi
wait_health

echo "2/6 qualificando um lead incerto do dev"
run_id=""
for lead_id in L042 L031; do
  accepted="$(api -X POST "$API_URL/v1/leads/qualify" -H 'Content-Type: application/json' \
    -d "$(lead_json "$lead_id")")" || fail "POST recusado"
  candidate="$(json_get run_id <<<"$accepted")"
  wait_status "$candidate"
  status="$(json_get status <<<"$run")"
  echo "   $lead_id run_id=$candidate status=$status tier=$(json_get tier <<<"$run")"
  if [[ "$status" == "needs_review" && -n "$(json_get review_requested_at <<<"$run")" ]]; then
    run_id="$candidate"; break
  fi
done
[[ -n "$run_id" ]] || fail "nenhum lead parou para revisão (variação do modelo): rode de novo"
tier_before="$(json_get tier <<<"$run")"

echo "3/6 reiniciando o container da API"
docker compose restart api
wait_health

echo "4/6 a execução continua esperando a revisão"
run="$(api "$API_URL/v1/runs/$run_id")"
[[ "$(json_get status <<<"$run")" == "needs_review" ]] || fail "status depois do restart: $(json_get status <<<"$run")"
[[ "$(api "$API_URL/v1/runs?status=needs_review&limit=100")" == *"$run_id"* ]] || fail "fora da fila de revisão"

echo "5/6 decisão humana (approve) e segunda decisão recusada"
decision='{"action": "approve", "reviewer": "Autor (teste da T31)", "comment": "restart do container"}'
api -X POST "$API_URL/v1/runs/$run_id/review" -H 'Content-Type: application/json' -d "$decision" >/dev/null \
  || fail "decisão recusada"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/v1/runs/$run_id/review" \
  -H @<(printf 'X-API-Key: %s\n' "$API_KEY") -H 'Content-Type: application/json' -d "$decision")"
[[ "$code" == "409" ]] || fail "esperado 409 na segunda decisão, veio $code"

echo "6/6 o grafo retomou do checkpoint"
wait_status "$run_id"
[[ "$(json_get status <<<"$run")" == "completed" ]] || fail "status final $(json_get status <<<"$run"): $(json_get errors <<<"$run")"
[[ "$(json_get result.review.reviewer <<<"$run")" == "Autor (teste da T31)" ]] || fail "revisão ausente no resultado"
[[ "$(json_get tier <<<"$run")" == "$tier_before" ]] || fail "approve mudou o tier"
echo "   tier=$tier_before (aprovado) · crm=$(json_get crm_ids <<<"$run") · custo=US\$$(json_get cost_usd <<<"$run")"
echo "OK: a execução sobreviveu ao restart do container e foi retomada com a decisão humana"
