#!/usr/bin/env bash
# Deploy da function de ingestao (rodar no Cloud Shell, dentro desta pasta).
# Uso: SODA_APP_TOKEN=xxxx bash deploy.sh
set -euo pipefail
PROJECT=pdm-crimes-chicago
REGION=us-central1
SA=sa-ingest@${PROJECT}.iam.gserviceaccount.com

gcloud functions deploy ingest-chicago \
  --gen2 --project "$PROJECT" --region "$REGION" \
  --runtime python312 --entry-point ingest --source . \
  --trigger-http --no-allow-unauthenticated \
  --memory 1Gi --timeout 3600s --max-instances 3 \
  --service-account "$SA" \
  --set-env-vars "BUCKET=crimes-chicago-pdm-2026,BRONZE_TABLE=${PROJECT}.crimes_chicago.tb_crimes_bronze_api,SODA_APP_TOKEN=${SODA_APP_TOKEN:-}"
