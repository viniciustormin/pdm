#!/usr/bin/env bash
# Deploy da API no Cloud Run.
#
# ⚠️  CUSTO: min-instances > 0 cobra mesmo parado. O padrão aqui é 0.
#     Antes da apresentação: ./deploy.sh --aquecer   (sobe min-instances=1)
#     Depois da apresentação: ./deploy.sh --esfriar  (volta para 0)
#
# Pré-requisitos:
#   - data/janelas_jogo.csv gerado (scripts/exportar_janelas.sh)
#   - modelo publicado no MODEL_URI
#   - a service account do Cloud Run com roles/storage.objectViewer no bucket
set -euo pipefail

PROJETO="${PROJETO:-pdm-crimes-chicago}"
REGIAO="${REGIAO:-us-central1}"
SERVICO="${SERVICO:-api-prisao}"
BUCKET="${BUCKET:-crimes-chicago-pdm-2026}"
MODEL_URI="${MODEL_URI:-gs://${BUCKET}/models/prisao/v0/model.joblib}"

aquecer() {
  echo ">> min-instances=1 em ${SERVICO} (PASSA A COBRAR PARADO)"
  gcloud run services update "${SERVICO}" \
    --project="${PROJETO}" --region="${REGIAO}" --min-instances=1
  echo ">> lembre de rodar ./deploy.sh --esfriar depois da apresentação"
}

esfriar() {
  echo ">> min-instances=0 em ${SERVICO}"
  gcloud run services update "${SERVICO}" \
    --project="${PROJETO}" --region="${REGIAO}" --min-instances=0
}

case "${1:-}" in
  --aquecer) aquecer; exit 0 ;;
  --esfriar) esfriar; exit 0 ;;
esac

# ---------------------------------------------------------------- validações
if [ ! -f data/janelas_jogo.csv ]; then
  echo "!! data/janelas_jogo.csv não existe. Rode scripts/exportar_janelas.sh" >&2
  exit 1
fi

# O repo traz um .exemplo com 6 linhas só para desenvolver. Publicar isso
# faria a API responder teve_jogo=false para quase tudo, em silêncio.
JANELAS=$(($(wc -l < data/janelas_jogo.csv) - 1))
if [ "${JANELAS}" -lt 1000 ]; then
  echo "!! data/janelas_jogo.csv tem só ${JANELAS} linhas — parece ser o arquivo" >&2
  echo "   de exemplo. A gold_janelas do T1 tem 5.404 janelas de jogo." >&2
  echo "   Rode scripts/exportar_janelas.sh antes do deploy." >&2
  exit 1
fi
echo ">> janelas de jogo: ${JANELAS}"

echo ">> rodando os testes antes de publicar"
python -m pytest tests/ -q

echo ">> deploy de ${SERVICO} em ${REGIAO}"
gcloud run deploy "${SERVICO}" \
  --project="${PROJETO}" \
  --source . \
  --region="${REGIAO}" \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --concurrency=20 \
  --timeout=60s \
  --min-instances=0 \
  --max-instances=3 \
  --set-env-vars="MODEL_URI=${MODEL_URI},JANELAS_CSV=data/janelas_jogo.csv,JANELAS_OPCIONAL=false,LIMIAR=0.5"

URL=$(gcloud run services describe "${SERVICO}" \
        --project="${PROJETO}" --region="${REGIAO}" --format='value(status.url)')

echo
echo ">> no ar em ${URL}"
echo ">> conferindo /health"
curl -fsS "${URL}/health" | python -m json.tool
echo
echo ">> URL para o README e para o teste de latência:"
echo "${URL}"
