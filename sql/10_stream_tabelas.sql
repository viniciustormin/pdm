-- Tabelas alimentadas pelo pipeline de streaming (Dataflow). O schema segue o JSON do evento
-- e as colunas da silver, para a view unificada juntar batch e stream sem conversao.

-- Eventos validos, ja limpos. Particao pela data da ocorrencia e cluster pelas mesmas
-- chaves da silver: as consultas de demo e a view unificada filtram por elas.
CREATE TABLE IF NOT EXISTS `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream` (
  unique_key              STRING  OPTIONS(description = 'id do evento na origem (SIM-... no simulador)'),
  event_id                STRING  OPTIONS(description = 'uuid da mensagem: chave de deduplicacao'),
  data_hora_local_chicago TIMESTAMP OPTIONS(description = 'hora de parede de Chicago, sem conversao (convencao do T1)'),
  data_ocorrencia         DATE,
  hora_ocorrencia         INT64,
  distrito_policial       INT64,
  beat                    INT64,
  tipo_crime              STRING,
  descricao_crime         STRING,
  local_ocorrencia        STRING,
  eh_domestico            BOOL,
  latitude                FLOAT64,
  longitude               FLOAT64,
  teve_jogo               BOOL    OPTIONS(description = 'reservado para o Trabalho Final'),
  prob_prisao             FLOAT64 OPTIONS(description = 'reservado: predicao da API, Trabalho Final'),
  _publicado_em           TIMESTAMP OPTIONS(description = 'quando o gerador publicou no Pub/Sub (UTC)'),
  _processado_em          TIMESTAMP OPTIONS(description = 'quando o Dataflow processou (UTC)')
)
PARTITION BY data_ocorrencia
CLUSTER BY distrito_policial, tipo_crime
OPTIONS(description = 'Crimes recebidos em tempo real via Pub/Sub + Dataflow');

-- Dead-letter: eventos rejeitados pela limpeza, com o motivo e o payload original.
CREATE TABLE IF NOT EXISTS `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream_erros` (
  _recebido_em TIMESTAMP,
  motivo       STRING,
  payload      STRING
)
PARTITION BY DATE(_recebido_em)
OPTIONS(description = 'Eventos invalidos descartados pelo pipeline de streaming');

-- Agregado em janelas fixas de 1 minuto (processamento com janela no Beam).
CREATE TABLE IF NOT EXISTS `pdm-crimes-chicago.crimes_chicago.tb_crimes_stream_agg_1min` (
  janela_inicio     TIMESTAMP,
  distrito_policial INT64,
  tipo_crime        STRING,
  n                 INT64
)
PARTITION BY DATE(janela_inicio)
CLUSTER BY distrito_policial
OPTIONS(description = 'Contagem de eventos por distrito e tipo, janela fixa de 60 s');
