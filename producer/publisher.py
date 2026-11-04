"""Gerador de eventos do streaming: replay acelerado dos crimes reais de Chicago.

Ideia (alinhada com o professor): o batch representa a historia consolidada; a partir
de uma DATA DE CORTE, os crimes reais sao "reapresentados" como se estivessem chegando
agora, em ordem cronologica e com o relogio acelerado. O dado e real, entao depois do
replay da para conferir o streaming contra o batch, registro a registro.

Fonte dos eventos:
  --fonte api      (padrao) API SODA oficial, a partir de --corte
  --fonte arquivo  um JSONL salvo antes com --salvar (plano B sem internet)

Exemplos:
  python publisher.py --corte 2026-10-01 --velocidade 1440            # 1 dia por minuto
  python publisher.py --corte 2026-10-01 --sujo 0.05 --duracao 300    # 5% de eventos invalidos
  python publisher.py --corte 2026-10-01 --salvar replay.jsonl --sem-publicar
  python publisher.py --fonte arquivo --arquivo replay.jsonl
"""
import argparse
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone

import requests
from google.cloud import pubsub_v1

SODA_URL = "https://data.cityofchicago.org/resource/ijzp-q8t2.json"
# `arrest` fica de fora de proposito: e o alvo do modelo e ainda nao se sabe no momento do evento
CAMPOS = ["id", "date", "primary_type", "description", "location_description",
          "domestic", "beat", "district", "latitude", "longitude"]


def ler_api(corte, fim, token=None):
    """Busca os crimes reais a partir do corte, em ordem cronologica, paginando."""
    where = f"date >= '{corte}T00:00:00'" + (f" AND date < '{fim}T00:00:00'" if fim else "")
    sessao = requests.Session()
    if token:
        sessao.headers["X-App-Token"] = token
    offset, eventos = 0, []
    while True:
        resp = sessao.get(SODA_URL, timeout=120, params={
            "$select": ",".join(CAMPOS), "$where": where,
            "$order": "date, :id", "$limit": 50000, "$offset": offset})
        resp.raise_for_status()
        pagina = resp.json()
        eventos.extend(pagina)
        if len(pagina) < 50000:
            return eventos
        offset += 50000


def ler_arquivo(caminho):
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(linha) for linha in f if linha.strip()]


def data_do_evento(evento):
    return datetime.strptime(evento["date"][:19], "%Y-%m-%dT%H:%M:%S")


def sujar(evento):
    """Gera um evento invalido de proposito, para mostrar a limpeza/dead-letter na demo."""
    e = dict(evento)
    defeito = random.choice(["distrito", "data", "tipo", "json"])
    if defeito == "distrito":
        e["district"], e["beat"] = "099", None
    elif defeito == "data":
        e["date"] = "31/02/2026 25:61"
    elif defeito == "tipo":
        e["primary_type"] = ""
    else:
        return '{"id": "' + str(e.get("id")) + '", "date": '      # JSON truncado
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projeto", default="pdm-crimes-chicago")
    ap.add_argument("--topico", default="crimes-eventos")
    ap.add_argument("--fonte", choices=["api", "arquivo"], default="api")
    ap.add_argument("--corte", default="2026-10-01", help="data de corte (AAAA-MM-DD)")
    ap.add_argument("--fim", default=None, help="data final exclusiva (opcional)")
    ap.add_argument("--arquivo", default="replay.jsonl")
    ap.add_argument("--velocidade", type=float, default=1440.0,
                    help="segundos simulados por segundo real (1440 = 1 dia por minuto)")
    ap.add_argument("--duracao", type=float, default=None, help="para depois de N segundos reais")
    ap.add_argument("--sujo", type=float, default=0.0, help="fracao de eventos invalidos (ex.: 0.05)")
    ap.add_argument("--salvar", default=None, help="salva os eventos lidos em JSONL")
    ap.add_argument("--sem-publicar", action="store_true", help="so le/salva, nao publica")
    ap.add_argument("--token", default=None, help="App Token da API SODA (opcional)")
    args = ap.parse_args()

    eventos = ler_api(args.corte, args.fim, args.token) if args.fonte == "api" else ler_arquivo(args.arquivo)
    eventos.sort(key=lambda e: (e["date"], e["id"]))
    if not eventos:
        sys.exit("nenhum evento a partir do corte")
    print(f"{len(eventos)} eventos de {eventos[0]['date'][:16]} a {eventos[-1]['date'][:16]}", flush=True)

    if args.salvar:
        with open(args.salvar, "w", encoding="utf-8") as f:
            for e in eventos:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"salvo em {args.salvar}")
    if args.sem_publicar:
        return

    publisher = pubsub_v1.PublisherClient()
    topico = publisher.topic_path(args.projeto, args.topico)
    t0_sim, t0_real = data_do_evento(eventos[0]), time.monotonic()
    enviados, erros, ultimo_log, futuros = 0, [], 0.0, []

    def ao_publicar(fut):
        try:
            fut.result()
        except Exception as exc:          # noqa: BLE001 - registra e segue
            erros.append(str(exc))

    for evento in eventos:
        # relogio simulado: espera ate o "momento" do evento chegar
        atraso = (data_do_evento(evento) - t0_sim).total_seconds() / args.velocidade
        espera = atraso - (time.monotonic() - t0_real)
        if espera > 0:
            time.sleep(espera)
        if args.duracao and time.monotonic() - t0_real > args.duracao:
            break

        corpo = sujar(evento) if random.random() < args.sujo else dict(evento)
        if isinstance(corpo, dict):
            corpo["event_id"] = str(uuid.uuid4())
            corpo["published_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            dados = json.dumps(corpo, ensure_ascii=False)
        else:
            dados = corpo
        fut = publisher.publish(topico, dados.encode("utf-8"),
                                origem="replay", versao_schema="1")
        fut.add_done_callback(ao_publicar)
        futuros.append(fut)
        enviados += 1

        agora = time.monotonic()
        if agora - ultimo_log >= 2:
            print(f"[{agora - t0_real:6.0f}s] relogio simulado {evento['date'][:16]} | "
                  f"enviados {enviados} | erros {len(erros)}", flush=True)
            ultimo_log = agora

    for fut in futuros:
        try:
            fut.result(timeout=60)
        except Exception:                  # noqa: BLE001 - ja contado no callback
            pass
    print(f"fim: {enviados} enviados, {len(erros)} erros de publicacao")


if __name__ == "__main__":
    main()
