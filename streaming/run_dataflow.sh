#!/usr/bin/env bash
# Sobe o pipeline no Dataflow (rodar no Cloud Shell, dentro desta pasta).
# Lembrete de custo: o job de streaming cobra enquanto estiver de pe.
# Para parar:  gcloud dataflow jobs drain <JOB_ID> --region us-central1
set -euo pipefail
PROJECT=pdm-crimes-chicago
REGION=us-central1
BUCKET=crimes-chicago-pdm-2026

python3 pipeline.py \
  --runner DataflowRunner \
  --project "$PROJECT" --region "$REGION" \
  --job_name "crimes-streaming-$(date +%Y%m%d-%H%M)" \
  --temp_location "gs://$BUCKET/dataflow/temp" \
  --staging_location "gs://$BUCKET/dataflow/staging" \
  --service_account_email "sa-dataflow@${PROJECT}.iam.gserviceaccount.com" \
  --max_num_workers 1 --machine_type n1-standard-1 \
  --setup_file ./setup.py
