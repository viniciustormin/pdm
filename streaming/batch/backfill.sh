#!/usr/bin/env bash
# Carga historica: um ano por chamada (cada chamada cabe no timeout de 60 min).
# Uso: bash backfill.sh [ano_inicial] [ano_final]
set -uo pipefail
INI=${1:-2001}; FIM=${2:-$(date +%Y)}
URL=$(gcloud functions describe ingest-chicago --gen2 --region us-central1 --format='value(serviceConfig.uri)')
for y in $(seq "$INI" "$FIM"); do
  echo "== $y"
  curl -sS -m 3700 -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    "$URL?mode=backfill&year=$y"
  echo
done
