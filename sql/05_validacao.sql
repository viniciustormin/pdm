-- Validacoes da ingestao batch (evidencias para os slides).

-- 5.1 Execucoes da function: quantas linhas cada run trouxe
SELECT _run_id, _mode, MIN(_ingested_at) AS quando, COUNT(*) AS linhas,
       COUNT(DISTINCT id) AS ids, MAX(updated_on) AS maior_updated_on
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api`
GROUP BY 1, 2 ORDER BY quando DESC;

-- 5.2 Contagem por ano na bronze nova x bronze do T1 (a da API: streaming/batch/validar_backfill.py)
SELECT COALESCE(n.ano, o.ano) AS ano, n.ids AS bronze_api, o.ids AS bronze_t1,
       n.ids - o.ids AS diferenca
FROM (SELECT SAFE_CAST(year AS INT64) AS ano, COUNT(DISTINCT id) AS ids
      FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api` GROUP BY 1) n
FULL JOIN (SELECT year AS ano, COUNT(DISTINCT unique_key) AS ids
      FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze` GROUP BY 1) o USING (ano)
ORDER BY ano;

-- 5.3 Registros reclassificados: ids que chegaram mais de uma vez com updated_on diferente
SELECT COUNT(*) AS ids_reclassificados
FROM (SELECT id FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_bronze_api`
      GROUP BY id HAVING COUNT(DISTINCT updated_on) > 1);

-- 5.4 Silver: unicidade e frescor
SELECT COUNT(*) AS linhas, COUNT(DISTINCT unique_key) AS ids,
       MAX(data_ocorrencia) AS ultimo_crime, MAX(updated_on) AS ultima_atualizacao
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_silver`;
