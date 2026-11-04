-- Reconstrucao completa da silver a partir da bronze da API (rodar uma vez, apos o backfill).
-- Gera a v2 AO LADO da silver do T1; a troca so acontece depois da comparacao (passo 3.3).

-- 3.1 Mapa beat -> distrito, agora derivado da bronze da API
--     (antes vinha da bronze do T1, que sera aposentada).
CREATE OR REPLACE TABLE `pdm-crimes-chicago.crimes_chicago.dim_beat_distrito` AS
SELECT beat, district AS distrito_policial
FROM (
  SELECT beat, district, ROW_NUMBER() OVER (PARTITION BY beat ORDER BY n DESC) AS rn
  FROM (
    SELECT SAFE_CAST(beat AS INT64) AS beat, SAFE_CAST(district AS INT64) AS district, COUNT(*) AS n
    FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api`
    WHERE SAFE_CAST(beat AS INT64) IS NOT NULL AND SAFE_CAST(district AS INT64) IS NOT NULL
    GROUP BY 1, 2
  )
)
WHERE rn = 1;

-- 3.2 Silver v2. Particao mensal pela data do crime (~310 particoes, longe do
--     limite de 10.000) e cluster pelas chaves de filtro da gold.
CREATE OR REPLACE TABLE `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
PARTITION BY DATE_TRUNC(data_ocorrencia, MONTH)
CLUSTER BY distrito_policial, tipo_crime
AS SELECT * FROM `pdm-crimes-chicago.crimes_chicago.fn_crimes_silver`(TIMESTAMP '1970-01-01');

-- 3.3 Comparacao com a silver do T1 (por ano)
SELECT ano,
       COUNTIF(origem = 't1') AS silver_t1,
       COUNTIF(origem = 'v2') AS silver_v2,
       COUNTIF(origem = 'v2') - COUNTIF(origem = 't1') AS diferenca
FROM (
  SELECT ano, 't1' AS origem FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`
  UNION ALL
  SELECT ano, 'v2' FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
)
GROUP BY ano ORDER BY ano;

-- 3.4 TROCA (feita em 21/10/2026, com o OK do grupo): backup da silver do T1 e promocao da v2.
-- A silver do T1 nao era particionada; o BigQuery nao troca a particao num CREATE OR REPLACE,
-- por isso o DROP + COPY, so depois de conferir que o backup tem o mesmo numero de linhas.
-- CREATE TABLE `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_bkp_t1`
--   COPY `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`;
-- DROP TABLE `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`;
-- CREATE TABLE `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`
--   COPY `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`;
