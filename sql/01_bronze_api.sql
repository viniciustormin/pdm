-- Bronze de crimes alimentada pela API oficial (SODA) da prefeitura de Chicago.
-- Append-only: cada execucao da function acrescenta linhas, nada e alterado.
-- Tudo STRING: a bronze guarda o dado como veio; tipagem e regra de negocio sao da silver.
-- Particao diaria por _ingested_at: cada execucao cai numa particao, o MERGE da
-- silver le so as particoes recentes.
CREATE TABLE IF NOT EXISTS `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api` (
  id STRING, case_number STRING, date STRING, block STRING, iucr STRING,
  primary_type STRING, description STRING, location_description STRING,
  arrest STRING, domestic STRING, beat STRING, district STRING, ward STRING,
  community_area STRING, fbi_code STRING, x_coordinate STRING, y_coordinate STRING,
  year STRING, updated_on STRING, latitude STRING, longitude STRING,
  _ingested_at TIMESTAMP OPTIONS(description = 'momento da execucao da ingestao (UTC)'),
  _run_id      STRING    OPTIONS(description = 'id da execucao da function'),
  _mode        STRING    OPTIONS(description = 'incremental ou backfill'),
  _source_file STRING    OPTIONS(description = 'arquivo NDJSON de origem no GCS')
)
PARTITION BY DATE(_ingested_at)
OPTIONS(description = 'Crimes de Chicago - bronze da API SODA ijzp-q8t2 (append-only)');
