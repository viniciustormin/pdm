-- Conferencia: o streaming processou certo? Como o replay usa crimes reais, cada evento
-- do stream tem um "gabarito" na silver (mesmo id). Rodar depois de um replay completo.

-- 12.1 Cobertura: quantas ocorrencias do periodo chegaram pelo stream
WITH s AS (
  SELECT DISTINCT SAFE_CAST(unique_key AS INT64) AS id
  FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream`
  WHERE data_ocorrencia >= DATE '2026-10-01'
), b AS (
  SELECT unique_key AS id FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`
  WHERE data_ocorrencia >= DATE '2026-10-01'
)
SELECT
  (SELECT COUNT(*) FROM b)                         AS no_batch,
  (SELECT COUNT(*) FROM s)                         AS no_stream,
  (SELECT COUNT(*) FROM b JOIN s USING (id))       AS em_ambos,
  (SELECT COUNT(*) FROM b LEFT JOIN s USING (id) WHERE s.id IS NULL) AS so_no_batch,
  (SELECT COUNT(*) FROM s LEFT JOIN b USING (id) WHERE b.id IS NULL) AS so_no_stream;

-- 12.2 Igualdade campo a campo (as regras de limpeza do Beam = regras da silver SQL)
SELECT
  COUNT(*)                                                         AS comparados,
  COUNTIF(s.data_hora_local_chicago != b.data_hora_local_chicago)  AS dif_data_hora,
  COUNTIF(s.distrito_policial != b.distrito_policial)              AS dif_distrito,
  COUNTIF(s.tipo_crime != b.tipo_crime)                            AS dif_tipo,
  COUNTIF(IFNULL(s.latitude, 0) != IFNULL(b.latitude, 0))          AS dif_latitude
FROM (
  SELECT * FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY unique_key ORDER BY _processado_em) = 1
) s
JOIN `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver` b
  ON SAFE_CAST(s.unique_key AS INT64) = b.unique_key;

-- 12.3 Latencia ponta a ponta (publicacao no Pub/Sub -> gravacao pelo Dataflow)
SELECT
  COUNT(*) AS eventos,
  APPROX_QUANTILES(TIMESTAMP_DIFF(_processado_em, _publicado_em, MILLISECOND), 100)[OFFSET(50)] AS p50_ms,
  APPROX_QUANTILES(TIMESTAMP_DIFF(_processado_em, _publicado_em, MILLISECOND), 100)[OFFSET(95)] AS p95_ms
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream`
WHERE _processado_em >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR);

-- 12.4 Rejeitados pela limpeza (dead-letter), por motivo
SELECT REGEXP_EXTRACT(motivo, r'^[^:]+') AS motivo, COUNT(*) AS n
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream_erros`
GROUP BY 1 ORDER BY n DESC;
