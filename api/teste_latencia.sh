#!/usr/bin/env bash
# 20 requisições no /predict, mediana e percentis. Evidência para docs/evidencias/.
#
# Uso:
#   ./teste_latencia.sh https://api-prisao-xxxx.us-central1.run.app
#   ./teste_latencia.sh                      (usa http://localhost:8080)
#
# Mede duas coisas distintas, e a diferença entre elas é o que você explica
# na demo:
#   latencia_ms  (corpo da resposta)  -> só o tempo de inferência
#   total        (curl)               -> inferência + rede + TLS
set -euo pipefail

URL="${1:-http://localhost:8080}"
N="${N:-20}"

PAYLOAD='{
  "tipo_crime": "THEFT",
  "local_ocorrencia": "STREET",
  "distrito_policial": 19,
  "data_hora_local_chicago": "2026-07-04T23:30:00",
  "eh_domestico": false
}'

echo ">> ${N} requisições em ${URL}/predict"
echo

# Primeira chamada fora da medição: paga o cold start e a conexão TLS, e
# incluí-la na mediana distorceria o resultado.
echo ">> aquecendo (resultado descartado)"
curl -fsS -o /dev/null -w "   cold start: %{time_total}s\n" \
  -X POST "${URL}/predict" -H 'Content-Type: application/json' -d "${PAYLOAD}"
echo

TMP=$(mktemp)
trap 'rm -f "${TMP}"' EXIT

for i in $(seq 1 "${N}"); do
  RESP=$(curl -fsS -w '\n%{time_total}' \
    -X POST "${URL}/predict" -H 'Content-Type: application/json' -d "${PAYLOAD}")
  TOTAL=$(printf '%s' "${RESP}" | tail -1)
  CORPO=$(printf '%s' "${RESP}" | sed '$d')
  INFER=$(printf '%s' "${CORPO}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["latencia_ms"])')
  # total vem em segundos; converte para ms
  printf '%s %s\n' "$(python3 -c "print(${TOTAL}*1000)")" "${INFER}" >> "${TMP}"
  printf '   %2d/%d  total %7.1f ms   inferência %6.3f ms\n' \
    "${i}" "${N}" "$(python3 -c "print(${TOTAL}*1000)")" "${INFER}"
done

echo
python3 - "${TMP}" <<'PY'
import statistics as st, sys
linhas = [l.split() for l in open(sys.argv[1]) if l.strip()]
total = sorted(float(a) for a, _ in linhas)
infer = sorted(float(b) for _, b in linhas)

def p(v, q):
    return v[min(int(len(v) * q), len(v) - 1)]

print("=" * 52)
print(f"{'':14}{'TOTAL (ms)':>14}{'INFERÊNCIA (ms)':>18}")
print("-" * 52)
for rot, f in (("mínimo", min), ("mediana", st.median), ("máximo", max)):
    print(f"{rot:14}{f(total):>14.2f}{f(infer):>18.3f}")
print(f"{'p95':14}{p(total,0.95):>14.2f}{p(infer,0.95):>18.3f}")
print("=" * 52)
print(f"n = {len(total)} requisições (cold start excluído)")
PY
