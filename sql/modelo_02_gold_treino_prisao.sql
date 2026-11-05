-- =============================================================================
-- modelo_02_gold_treino_prisao.sql — base de treino do modelo de prisão
--
-- Rode só depois de conferir o modelo_01_diagnostico.sql, em especial D3 e D6.
--
-- Convenções que a API repete em api/app/features.py:
--   tipo_crime, local_ocorrencia  UPPER(TRIM())
--   hora                          0-23, horário de parede de Chicago
--   dia_semana                    1 = domingo ... 7 = sábado
--   mes                           1-12
--   teve_jogo                     mesmo distrito e janela_ini <= t < janela_fim,
--                                 só em janelas de jogo; controles contam como FALSE
--
-- Partição por ano: o treino lê um split por vez, então cada leitura só varre
-- os anos daquele split. Também torna a separação temporal visível na tabela.
-- =============================================================================

-- Depois da última janela conhecida, teve_jogo seria FALSE por falta de
-- calendário, não por falta de jogo. Esses crimes ficam fora da base.
DECLARE fim_cobertura DATETIME DEFAULT (
  SELECT MAX(janela_fim)
  FROM `pdm-crimes-chicago.crimes_chicago.gold_janelas`
  WHERE teve_jogo
);

CREATE OR REPLACE TABLE `pdm-crimes-chicago.crimes_chicago.gold_treino_prisao`
PARTITION BY RANGE_BUCKET(ano, GENERATE_ARRAY(2021, 2027, 1))
OPTIONS (description = 'Base de treino do modelo de prisão. Uma linha por ocorrência.')
AS

WITH base AS (
  SELECT
    unique_key,
    UPPER(TRIM(tipo_crime))                                  AS tipo_crime,
    -- A API exige texto não vazio, e categoria desconhecida é aceita pelo modelo.
    COALESCE(NULLIF(UPPER(TRIM(local_ocorrencia)), ''), 'NAO_INFORMADO') AS local_ocorrencia,
    distrito_policial,
    hora_ocorrencia                                          AS hora,
    EXTRACT(DAYOFWEEK FROM data_ocorrencia)                  AS dia_semana,
    EXTRACT(MONTH     FROM data_ocorrencia)                  AS mes,
    -- O campo eh_domestico da API também assume FALSE quando não é informado.
    IFNULL(eh_domestico, FALSE)                              AS eh_domestico,
    houve_prisao,
    EXTRACT(YEAR FROM data_ocorrencia)                       AS ano,
    -- O TIMESTAMP guarda o horário de Chicago como se fosse UTC (conferir em D3).
    DATETIME(data_hora_local_chicago, 'UTC')                 AS dt_local
  FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver_v2`
  WHERE data_ocorrencia >= DATE '2021-01-01'
    AND data_ocorrencia <  DATE '2027-01-01'
    AND data_hora_local_chicago IS NOT NULL
    AND tipo_crime              IS NOT NULL
    AND distrito_policial       IS NOT NULL
    AND hora_ocorrencia         IS NOT NULL
    AND houve_prisao            IS NOT NULL
    AND DATETIME(data_hora_local_chicago, 'UTC') < fim_cobertura
  -- Uma linha por ocorrência, mantendo a versão mais recente.
  QUALIFY ROW_NUMBER() OVER (PARTITION BY unique_key ORDER BY updated_on DESC) = 1
),

-- DISTINCT evita multiplicar crimes em janelas sobrepostas (doubleheaders).
crimes_com_jogo AS (
  SELECT DISTINCT b.unique_key
  FROM base b
  JOIN `pdm-crimes-chicago.crimes_chicago.gold_janelas` w
    ON  w.distrito_policial = b.distrito_policial
    AND b.dt_local >= w.janela_ini
    AND b.dt_local <  w.janela_fim
  WHERE w.teve_jogo
)

SELECT
  b.unique_key,
  b.tipo_crime,
  b.local_ocorrencia,
  b.distrito_policial,
  b.hora,
  b.dia_semana,
  b.mes,
  b.eh_domestico,
  j.unique_key IS NOT NULL                                   AS teve_jogo,
  b.houve_prisao,
  b.ano,
  CASE
    WHEN b.ano BETWEEN 2021 AND 2024 THEN 'TREINO'
    WHEN b.ano = 2025                THEN 'VALIDACAO'
    WHEN b.ano = 2026                THEN 'TESTE'
  END                                                        AS split
FROM base b
LEFT JOIN crimes_com_jogo j USING (unique_key);
