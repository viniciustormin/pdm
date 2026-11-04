-- Regras da silver de crimes num lugar so: uma table function usada tanto na
-- reconstrucao completa (03) quanto no MERGE diario (04). Mesmas regras do T1
-- (entregavel_PDM_T1/02_silver/05_crimes_silver.sql), agora a partir da bronze da API.
--
--   * tipagem: a bronze e toda STRING
--   * dedup por id, ficando com o `updated_on` mais recente (reclassificacoes)
--   * distrito faltante recuperado pelo beat (dim_beat_distrito)
--   * coordenadas fora da caixa de Chicago viram NULL
--   * so distritos 1..25
--
-- Fuso: a API devolve horario de parede de Chicago SEM fuso. Fazemos o parse sem
-- conversao, mantendo a convencao do T1 (a gold le com TZ='UTC').
-- Parametro `desde`: le so a bronze ingerida a partir desse instante (poda de particao).

CREATE OR REPLACE TABLE FUNCTION `pdm-crimes-chicago.crimes_chicago.fn_crimes_silver`(desde TIMESTAMP) AS (
  WITH tipada AS (
    SELECT
      SAFE_CAST(id AS INT64)                                   AS unique_key,
      SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S', date)        AS data_hora_local_chicago,
      SAFE_CAST(district AS INT64)                             AS district,
      SAFE_CAST(beat AS INT64)                                 AS beat,
      primary_type, description, location_description,
      SAFE_CAST(arrest AS BOOL)                                AS arrest,
      SAFE_CAST(domestic AS BOOL)                              AS domestic,
      SAFE_CAST(latitude AS FLOAT64)                           AS latitude,
      SAFE_CAST(longitude AS FLOAT64)                          AS longitude,
      SAFE_CAST(year AS INT64)                                 AS year,
      SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S', updated_on)  AS updated_on,
      _ingested_at
    FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api`
    WHERE _ingested_at >= desde
  ),
  dedup AS (
    SELECT * FROM tipada
    WHERE unique_key IS NOT NULL AND data_hora_local_chicago IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY unique_key ORDER BY updated_on DESC, _ingested_at DESC) = 1
  ),
  com_distrito AS (
    SELECT d.*, COALESCE(d.district, m.distrito_policial) AS distrito_final
    FROM dedup d
    LEFT JOIN `pdm-crimes-chicago.crimes_chicago.dim_beat_distrito` m ON d.beat = m.beat
  )
  SELECT
    unique_key,
    data_hora_local_chicago,
    DATE(data_hora_local_chicago)                AS data_ocorrencia,
    EXTRACT(HOUR FROM data_hora_local_chicago)   AS hora_ocorrencia,
    distrito_final                               AS distrito_policial,
    beat,
    primary_type                                 AS tipo_crime,
    description                                  AS descricao_crime,
    location_description                         AS local_ocorrencia,
    arrest                                       AS houve_prisao,
    domestic                                     AS eh_domestico,
    IF(latitude BETWEEN 41.64 AND 42.03 AND longitude BETWEEN -87.95 AND -87.52, latitude,  NULL) AS latitude,
    IF(latitude BETWEEN 41.64 AND 42.03 AND longitude BETWEEN -87.95 AND -87.52, longitude, NULL) AS longitude,
    year                                         AS ano,
    updated_on
  FROM com_distrito
  WHERE distrito_final BETWEEN 1 AND 25
);
