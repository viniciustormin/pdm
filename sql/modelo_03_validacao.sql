-- =============================================================================
-- modelo_03_validacao.sql — conferências DEPOIS de criar a gold_treino_prisao
-- =============================================================================

-- V1. Tamanho e taxas por split. Esperado: linhas = chaves e nenhum ano fora do split.
SELECT
  split,
  COUNT(*)                                                   AS linhas,
  COUNT(DISTINCT unique_key)                                 AS chaves,
  MIN(ano)                                                   AS ano_min,
  MAX(ano)                                                   AS ano_max,
  ROUND(AVG(CAST(houve_prisao AS INT64)), 4)                 AS taxa_prisao,
  COUNTIF(teve_jogo)                                         AS linhas_com_jogo,
  ROUND(AVG(CAST(teve_jogo AS INT64)), 4)                    AS taxa_com_jogo
FROM `pdm-crimes-chicago.crimes_chicago.gold_treino_prisao`
GROUP BY split
ORDER BY ano_min;


-- V2. Faixas e nulos. Esperado: todas as colunas iguais a zero.
SELECT
  COUNTIF(split IS NULL)                                     AS split_nulo,
  COUNTIF(tipo_crime IS NULL OR local_ocorrencia IS NULL)    AS texto_nulo,
  COUNTIF(tipo_crime != UPPER(TRIM(tipo_crime)))             AS tipo_sem_padrao,
  COUNTIF(local_ocorrencia != UPPER(TRIM(local_ocorrencia))) AS local_sem_padrao,
  COUNTIF(distrito_policial NOT BETWEEN 1 AND 31)            AS distrito_fora_api,
  COUNTIF(hora NOT BETWEEN 0 AND 23)                         AS hora_invalida,
  COUNTIF(dia_semana NOT BETWEEN 1 AND 7)                    AS dia_invalido,
  COUNTIF(mes NOT BETWEEN 1 AND 12)                          AS mes_invalido
FROM `pdm-crimes-chicago.crimes_chicago.gold_treino_prisao`;


-- V3. Onde teve_jogo aparece. Esperado: TRUE só nos distritos dos estádios.
SELECT
  distrito_policial,
  COUNT(*)                                                   AS linhas,
  COUNTIF(teve_jogo)                                         AS com_jogo,
  ROUND(AVG(IF(teve_jogo,     CAST(houve_prisao AS INT64), NULL)), 4) AS taxa_com_jogo,
  ROUND(AVG(IF(NOT teve_jogo, CAST(houve_prisao AS INT64), NULL)), 4) AS taxa_sem_jogo
FROM `pdm-crimes-chicago.crimes_chicago.gold_treino_prisao`
GROUP BY distrito_policial
ORDER BY com_jogo DESC, distrito_policial;
