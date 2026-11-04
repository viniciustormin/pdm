#!/usr/bin/env bash
# Agendamentos do pipeline batch (rodar uma vez no Cloud Shell, na raiz do repo).
#  1) Cloud Scheduler: ingestao incremental diaria as 07:00 (America/Chicago), com OIDC
#  2) Consulta programada do BigQuery: MERGE bronze -> silver diario as 14:00 UTC
#     (depois da ingestao em qualquer horario de verao/inverno de Chicago)
set -euo pipefail
PROJECT=pdm-crimes-chicago
REGION=us-central1
SA_SCHED=sa-scheduler@${PROJECT}.iam.gserviceaccount.com
SA_INGEST=sa-ingest@${PROJECT}.iam.gserviceaccount.com
URL=$(gcloud functions describe ingest-chicago --gen2 --region "$REGION" --format='value(serviceConfig.uri)')

gcloud iam service-accounts describe "$SA_SCHED" >/dev/null 2>&1 || \
  gcloud iam service-accounts create sa-scheduler --display-name="Dispara a ingestao batch"
gcloud run services add-iam-policy-binding ingest-chicago --region "$REGION" \
  --member="serviceAccount:$SA_SCHED" --role=roles/run.invoker >/dev/null

gcloud scheduler jobs create http ingest-chicago-diario --location "$REGION" \
  --schedule="0 7 * * *" --time-zone="America/Chicago" \
  --uri="${URL}?mode=incremental" --http-method=GET \
  --oidc-service-account-email="$SA_SCHED" --oidc-token-audience="$URL" \
  --attempt-deadline=30m \
  --description="Ingestao incremental dos crimes de Chicago (API SODA -> GCS -> bronze)"

gcloud services enable bigquerydatatransfer.googleapis.com
PARAMS=$(python3 -c 'import json;print(json.dumps({"query": open("sql/04_merge_silver.sql").read()}))')
bq mk --transfer_config --project_id="$PROJECT" --location=US \
  --data_source=scheduled_query --display_name="merge_silver_crimes_diario" \
  --schedule="every day 14:00" --service_account_name="$SA_INGEST" \
  --params="$PARAMS"
