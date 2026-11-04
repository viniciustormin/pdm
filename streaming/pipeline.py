"""Pipeline de streaming: Pub/Sub -> limpeza -> BigQuery (Apache Beam / Dataflow).

    ReadFromPubSub (assinatura crimes-eventos-dataflow)
      -> LimparEvento (DoFn com duas saidas: ok / erro)
          ok   -> tb_crimes_stream
               -> janela fixa de 60 s -> contagem por (distrito, tipo) -> tb_crimes_stream_agg_1min
          erro -> tb_crimes_stream_erros   (dead-letter: nenhum evento some)

Execucao local:  python pipeline.py --runner DirectRunner  ...
Dataflow:        bash run_dataflow.sh
"""
import argparse
import logging

import apache_beam as beam
from apache_beam import window
from apache_beam.options.pipeline_options import PipelineOptions, StandardOptions

from transforms import EventoInvalido, limpar_evento, linha_de_erro

PROJETO = "pdm-crimes-chicago"
DATASET = "crimes_chicago"


class LimparEvento(beam.DoFn):
    """Aplica as regras da silver a cada mensagem. Saida principal: linhas validas;
    saida 'erro': linhas para a tabela de dead-letter."""

    ERRO = "erro"

    def __init__(self, tabela_dim):
        self.tabela_dim = tabela_dim
        self.beat_para_distrito = {}

    def setup(self):
        # Mapa beat -> distrito carregado uma vez por worker (dimensao pequena, ~300 linhas)
        from google.cloud import bigquery
        linhas = bigquery.Client(project=PROJETO).query(
            f"SELECT beat, distrito_policial FROM `{self.tabela_dim}`").result()
        self.beat_para_distrito = {r.beat: r.distrito_policial for r in linhas}
        logging.info("dim_beat_distrito carregada: %s beats", len(self.beat_para_distrito))

    def process(self, mensagem):
        try:
            yield limpar_evento(mensagem, self.beat_para_distrito)
        except EventoInvalido as exc:
            yield beam.pvalue.TaggedOutput(self.ERRO, linha_de_erro(mensagem, str(exc)))


class FormatarAgregado(beam.DoFn):
    def process(self, elemento, janela=beam.DoFn.WindowParam):
        (distrito, tipo), n = elemento
        yield {
            "janela_inicio": janela.start.to_utc_datetime().isoformat(),
            "distrito_policial": distrito,
            "tipo_crime": tipo,
            "n": n,
        }


def gravar(tabela):
    return beam.io.WriteToBigQuery(
        tabela,
        create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,   # schema vem do SQL
        write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
        method=beam.io.WriteToBigQuery.Method.STREAMING_INSERTS,
    )


def montar(p, args):
    resultado = (
        p
        | "LerPubSub" >> beam.io.ReadFromPubSub(subscription=args.assinatura)
        | "Limpar" >> beam.ParDo(LimparEvento(args.tabela_dim)).with_outputs(
            LimparEvento.ERRO, main="ok")
    )

    resultado.ok | "GravarStream" >> gravar(args.tabela_stream)
    resultado[LimparEvento.ERRO] | "GravarErros" >> gravar(args.tabela_erros)

    (
        resultado.ok
        | "Janela1min" >> beam.WindowInto(window.FixedWindows(60))
        | "ChaveDistritoTipo" >> beam.Map(lambda r: ((r["distrito_policial"], r["tipo_crime"]), 1))
        | "Contar" >> beam.CombinePerKey(sum)
        | "Formatar" >> beam.ParDo(FormatarAgregado())
        | "GravarAgregado" >> gravar(args.tabela_agg)
    )


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--assinatura",
                        default=f"projects/{PROJETO}/subscriptions/crimes-eventos-dataflow")
    parser.add_argument("--tabela_stream", default=f"{PROJETO}:{DATASET}.tb_crimes_stream")
    parser.add_argument("--tabela_erros", default=f"{PROJETO}:{DATASET}.tb_crimes_stream_erros")
    parser.add_argument("--tabela_agg", default=f"{PROJETO}:{DATASET}.tb_crimes_stream_agg_1min")
    parser.add_argument("--tabela_dim", default=f"{PROJETO}.{DATASET}.dim_beat_distrito")
    args, beam_args = parser.parse_known_args(argv)

    opcoes = PipelineOptions(beam_args, save_main_session=True)
    opcoes.view_as(StandardOptions).streaming = True
    with beam.Pipeline(options=opcoes) as p:
        montar(p, args)


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    main()
