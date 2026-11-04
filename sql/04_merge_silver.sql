-- MERGE diario bronze_api -> silver (consulta programada, 08:00 America/Chicago,
-- uma hora depois da ingestao incremental das 07:00).
-- Le so as particoes dos ultimos 2 dias da bronze (folga para uma execucao
-- atrasada). Idempotente: rodar duas vezes nao duplica nem regride registro,
-- porque so atualiza quando o `updated_on` que chega e mais novo.
MERGE `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver` T
USING (
  SELECT * FROM `pdm-crimes-chicago.crimes_chicago.fn_crimes_silver`(
    TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 DAY))
) S
ON T.unique_key = S.unique_key
WHEN MATCHED AND (T.updated_on IS NULL OR S.updated_on > T.updated_on) THEN UPDATE SET
  data_hora_local_chicago = S.data_hora_local_chicago,
  data_ocorrencia   = S.data_ocorrencia,
  hora_ocorrencia   = S.hora_ocorrencia,
  distrito_policial = S.distrito_policial,
  beat              = S.beat,
  tipo_crime        = S.tipo_crime,
  descricao_crime   = S.descricao_crime,
  local_ocorrencia  = S.local_ocorrencia,
  houve_prisao      = S.houve_prisao,
  eh_domestico      = S.eh_domestico,
  latitude          = S.latitude,
  longitude         = S.longitude,
  ano               = S.ano,
  updated_on        = S.updated_on
WHEN NOT MATCHED THEN INSERT ROW;
