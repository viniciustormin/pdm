-- Consultas para rodar AO VIVO enquanto o gerador publica.

-- 1. O streaming crescendo ao lado do historico batch (rodar varias vezes)
SELECT origem, COUNT(*) AS ocorrencias, MAX(data_hora_local_chicago) AS ultima_ocorrencia
FROM `pdm-crimes-chicago.crimes_chicago.vw_crimes_unificado`
WHERE data_ocorrencia >= DATE '2026-09-01'
GROUP BY origem;

-- 2. Ultimos eventos processados e a latencia de cada um
SELECT _processado_em, unique_key, data_hora_local_chicago, distrito_policial, tipo_crime,
       TIMESTAMP_DIFF(_processado_em, _publicado_em, MILLISECOND) AS latencia_ms
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream`
ORDER BY _processado_em DESC
LIMIT 10;

-- 3. Agregado em janelas de 1 minuto feito pelo Dataflow
SELECT janela_inicio, SUM(n) AS eventos, COUNT(DISTINCT distrito_policial) AS distritos
FROM `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream_agg_1min`
GROUP BY 1 ORDER BY 1 DESC LIMIT 10;

-- 4. Batch e stream juntos: crimes por dia em torno do corte (o "degrau" e a troca de pipeline)
SELECT data_ocorrencia, origem, COUNT(*) AS n
FROM `pdm-crimes-chicago.crimes_chicago.vw_crimes_unificado`
WHERE data_ocorrencia BETWEEN DATE '2026-09-24' AND DATE '2026-10-12'
GROUP BY 1, 2 ORDER BY 1;
