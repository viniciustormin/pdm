#!/usr/bin/env bash
# Exporta as janelas de JOGO da gold_janelas (T1) para o CSV que a API carrega
# em memória no startup.
#
# Por que CSV embarcado e não consulta ao BigQuery a cada request: são ~5.400
# janelas, menos de 1 MB. Cabe na memória do container e a consulta vira busca
# binária. Ir ao BigQuery por request adicionaria centenas de milissegundos à
# latência, que é justamente o que está sendo avaliado na demo.
#
# Rode isto sempre que a gold_janelas for recriada, e refaça o deploy.
set -euo pipefail

PROJETO="${PROJETO:-pdm-crimes-chicago}"
DATASET="${DATASET:-crimes_chicago}"
SAIDA="${SAIDA:-data/janelas_jogo.csv}"

mkdir -p "$(dirname "$SAIDA")"

echo ">> exportando janelas de jogo de ${PROJETO}.${DATASET}.gold_janelas"

bq query \
  --project_id="${PROJETO}" \
  --use_legacy_sql=false \
  --format=csv \
  --max_rows=1000000 \
  "SELECT
     CAST(id_janela AS STRING) AS id_janela,
     distrito_policial,
     FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', janela_ini) AS janela_ini,
     FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', janela_fim) AS janela_fim,
     teve_jogo,
     IFNULL(liga, '')      AS liga,
     IFNULL(time_casa, '') AS time_casa
   FROM \`${PROJETO}.${DATASET}.gold_janelas\`
   WHERE teve_jogo
   ORDER BY distrito_policial, janela_ini" > "${SAIDA}"

LINHAS=$(($(wc -l < "${SAIDA}") - 1))
echo ">> ${SAIDA}: ${LINHAS} janelas"
echo ">> tamanho: $(du -h "${SAIDA}" | cut -f1)"

if [ "${LINHAS}" -lt 1000 ]; then
  echo "!! ATENÇÃO: menos de 1.000 janelas. A gold_janelas do T1 tem 5.404 de jogo." >&2
  exit 1
fi
