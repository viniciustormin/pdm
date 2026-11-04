-- =============================================================================
-- modelo_01_diagnostico.sql — conferências ANTES de criar a gold_treino_prisao
-- Silver usada: tb_crimes_silver_v2. Nada aqui cria ou altera tabela.
-- Rode cada bloco separadamente e envie o resultado de todos.
-- =============================================================================

-- D1. Schema, partição e cluster reais das tabelas usadas.
SELECT table_name, ordinal_position, column_name, data_type,
       is_partitioning_column, clustering_ordinal_position
FROM `pdm-crimes-chicago.crimes_chicago.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name IN ('tb_crimes_silver_v2', 'gold_janelas')
ORDER BY table_name, ordinal_position;


-- D2. Volume, cobertura, chave e alvo por ano do split.
--     dif_ano > 0 significa que `ano` não bate com data_ocorrencia.
SELECT
  EXTRACT(YEAR FROM data_ocorrencia)                         AS ano_data,
  COUNT(*)                                                   AS n,
  COUNT(DISTINCT unique_key)                                 AS chaves_distintas,
  COUNTIF(ano != EXTRACT(YEAR FROM data_ocorrencia))         AS dif_ano,
  COUNTIF(houve_prisao IS NULL)                              AS alvo_nulo,
  ROUND(AVG(CAST(houve_prisao AS INT64)), 4)                 AS taxa_prisao,
  MIN(data_ocorrencia)                                       AS primeira_data,
  MAX(data_ocorrencia)                                       AS ultima_data
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
WHERE data_ocorrencia >= DATE '2021-01-01'
GROUP BY ano_data
ORDER BY ano_data;


-- D3. Fuso da v2. No T1, o horário de Chicago estava gravado como se fosse UTC.
--     A v2 foi recriada pela API, então a convenção precisa ser confirmada.
--     Esperado: colunas *_utc iguais a n. Se não forem, NÃO crie a gold.
SELECT
  COUNT(*)                                                                                   AS n,
  COUNTIF(data_hora_local_chicago IS NULL)                                                   AS ts_nulo,
  COUNTIF(hora_ocorrencia = EXTRACT(HOUR FROM data_hora_local_chicago AT TIME ZONE 'UTC'))   AS hora_utc,
  COUNTIF(hora_ocorrencia = EXTRACT(HOUR FROM data_hora_local_chicago AT TIME ZONE 'America/Chicago')) AS hora_chicago,
  COUNTIF(data_ocorrencia = DATE(data_hora_local_chicago, 'UTC'))                            AS data_utc,
  COUNTIF(data_ocorrencia = DATE(data_hora_local_chicago, 'America/Chicago'))                AS data_chicago
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
WHERE data_ocorrencia >= DATE '2021-01-01';


-- D4. Nulos, faixas e cardinalidade das features.
SELECT
  COUNTIF(tipo_crime IS NULL)                                AS tipo_nulo,
  COUNT(DISTINCT UPPER(TRIM(tipo_crime)))                    AS tipo_distintos,
  COUNTIF(local_ocorrencia IS NULL OR TRIM(local_ocorrencia) = '') AS local_vazio,
  COUNT(DISTINCT UPPER(TRIM(local_ocorrencia)))              AS local_distintos,
  COUNTIF(distrito_policial IS NULL)                         AS distrito_nulo,
  COUNT(DISTINCT distrito_policial)                          AS distrito_distintos,
  MIN(distrito_policial)                                     AS distrito_min,
  MAX(distrito_policial)                                     AS distrito_max,
  COUNTIF(hora_ocorrencia IS NULL OR hora_ocorrencia NOT BETWEEN 0 AND 23) AS hora_invalida,
  COUNTIF(eh_domestico IS NULL)                              AS domestico_nulo
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
WHERE data_ocorrencia >= DATE '2021-01-01';


-- D5. Taxa mensal desde 2025. Queda só nos meses finais pode indicar que
--     prisões recentes ainda não foram registradas, o que afetaria o teste.
SELECT
  DATE_TRUNC(data_ocorrencia, MONTH)                         AS mes,
  COUNT(*)                                                   AS n,
  ROUND(AVG(CAST(houve_prisao AS INT64)), 4)                 AS taxa_prisao
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
WHERE data_ocorrencia >= DATE '2025-01-01'
GROUP BY mes
ORDER BY mes;


-- D6. Cobertura das janelas de jogo por ano e liga. Depois da última janela,
--     todo crime viraria teve_jogo = FALSE, mesmo com jogo acontecendo.
SELECT
  EXTRACT(YEAR FROM janela_ini)                              AS ano,
  liga,
  COUNT(*)                                                   AS janelas,
  STRING_AGG(DISTINCT CAST(distrito_policial AS STRING), ',') AS distritos,
  MIN(janela_ini)                                            AS inicio,
  MAX(janela_fim)                                            AS fim
FROM `pdm-crimes-chicago.crimes_chicago.gold_janelas`
WHERE teve_jogo AND janela_ini >= DATETIME '2021-01-01'
GROUP BY ano, liga
ORDER BY ano, liga;


-- D7. Sinal de teve_jogo: taxa de prisão em janelas de jogo contra controles
--     pareados do T1, por distrito. Cada crime conta uma vez por condição.
WITH crimes_em_janela AS (
  SELECT DISTINCT
    w.teve_jogo,
    c.distrito_policial,
    c.unique_key,
    c.houve_prisao
  FROM `pdm-crimes-chicago.crimes_chicago.gold_janelas` w
  JOIN `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2` c
    ON  c.distrito_policial = w.distrito_policial
    AND DATETIME(c.data_hora_local_chicago, 'UTC') >= w.janela_ini
    AND DATETIME(c.data_hora_local_chicago, 'UTC') <  w.janela_fim
  WHERE c.data_ocorrencia >= DATE '2021-01-01'
    AND w.janela_ini      >= DATETIME '2021-01-01'
)
SELECT
  distrito_policial,
  teve_jogo,
  COUNT(*)                                                   AS n_crimes,
  ROUND(AVG(CAST(houve_prisao AS INT64)), 4)                 AS taxa_prisao
FROM crimes_em_janela
GROUP BY distrito_policial, teve_jogo
ORDER BY distrito_policial, teve_jogo;


-- D8. A tb_crimes_silver foi criada depois da v2 e do backup do T1. Esta consulta
--     mostra se ela é hoje uma cópia da v2 ou outra base.
SELECT
  COUNT(v.chave_v2)                                          AS n_v2,
  COUNT(a.chave_silver)                                      AS n_silver,
  COUNTIF(v.chave_v2 IS NOT NULL AND a.chave_silver IS NOT NULL) AS em_ambas,
  COUNTIF(v.prisao_v2 != a.prisao_silver)                    AS alvo_diferente
FROM (
  SELECT unique_key AS chave_v2, houve_prisao AS prisao_v2
  FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
  WHERE data_ocorrencia >= DATE '2021-01-01'
) v
FULL OUTER JOIN (
  SELECT unique_key AS chave_silver, houve_prisao AS prisao_silver
  FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`
  WHERE data_ocorrencia >= DATE '2021-01-01'
) a
  ON v.chave_v2 = a.chave_silver;
