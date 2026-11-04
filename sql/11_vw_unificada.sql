-- View unificada batch + streaming (requisito "Batch + Streaming evidente no BigQuery").
--
-- Data de corte: ate 30/09/2026 o historico vem do batch (silver, alimentada pela API
-- oficial); a partir de 01/10/2026 os crimes chegam pelo streaming (replay acelerado
-- dos eventos reais via Pub/Sub + Dataflow). A silver continua completa (o modelo usa
-- tudo); o corte so define de qual pipeline cada periodo e lido aqui.
CREATE OR REPLACE VIEW `pdm-crimes-chicago.crimes_chicago.vw_crimes_unificado` AS
WITH corte AS (SELECT DATE '2026-10-01' AS data_corte)
SELECT
  'batch'                     AS origem,
  CAST(unique_key AS STRING)  AS unique_key,
  data_hora_local_chicago, data_ocorrencia, hora_ocorrencia,
  distrito_policial, beat, tipo_crime, descricao_crime, local_ocorrencia,
  eh_domestico, latitude, longitude,
  CAST(NULL AS TIMESTAMP)     AS _publicado_em,
  CAST(NULL AS TIMESTAMP)     AS _processado_em
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`, corte
WHERE data_ocorrencia < corte.data_corte
UNION ALL
SELECT
  'stream', unique_key,
  data_hora_local_chicago, data_ocorrencia, hora_ocorrencia,
  distrito_policial, beat, tipo_crime, descricao_crime, local_ocorrencia,
  eh_domestico, latitude, longitude,
  _publicado_em, _processado_em
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream`, corte
WHERE data_ocorrencia >= corte.data_corte
-- o mesmo evento pode chegar duas vezes (entrega "pelo menos uma vez" do Pub/Sub, ou
-- replay repetido): fica a primeira chegada de cada ocorrencia
QUALIFY ROW_NUMBER() OVER (PARTITION BY unique_key ORDER BY _processado_em) = 1;
