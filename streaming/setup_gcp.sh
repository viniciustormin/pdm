#!/usr/bin/env bash
# Infra do streaming (rodar uma vez no Cloud Shell, na raiz do repo).
set -euo pipefail
PROJECT=pdm-crimes-chicago
BUCKET=crimes-chicago-pdm-2026
SA=sa-dataflow@${PROJECT}.iam.gserviceaccount.com

gcloud services enable pubsub.googleapis.com dataflow.googleapis.com compute.googleapis.com

# Topico + duas assinaturas (Pub/Sub e "um para muitos"): uma para o pipeline, outra para
# espiar as mensagens chegando durante a demo.
gcloud pubsub topics create crimes-eventos --message-retention-duration=1d
gcloud pubsub subscriptions create crimes-eventos-dataflow --topic=crimes-eventos \
  --ack-deadline=60 --message-retention-duration=1d
gcloud pubsub subscriptions create crimes-eventos-debug --topic=crimes-eventos \
  --ack-deadline=30 --message-retention-duration=1h

# Tabelas do streaming e view unificada batch + stream
bq query --use_legacy_sql=false < sql/10_stream_tabelas.sql
bq query --use_legacy_sql=false < sql/11_vw_unificada.sql

# Conta de servico dos workers do Dataflow (permissao minima)
gcloud iam service-accounts create sa-dataflow --display-name="Workers do pipeline de streaming"
sleep 5
for R in roles/dataflow.worker roles/pubsub.subscriber roles/bigquery.dataEditor roles/bigquery.jobUser; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
    --role="$R" --condition=None --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin >/dev/null
echo "infra do streaming pronta"
