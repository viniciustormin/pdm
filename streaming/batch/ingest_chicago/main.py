"""Ingestao batch dos crimes de Chicago pela API oficial da prefeitura (SODA).

Cloud Run function (HTTP). Dois modos:
  ?mode=incremental          (padrao) busca o que foi criado/alterado desde a
                             ultima carga, usando `updated_on` como marca d'agua.
  ?mode=backfill&year=AAAA   carga historica de um ano inteiro.

Fluxo de cada execucao:
  API SODA (paginada) -> NDJSON no GCS (camada raw, imutavel)
                      -> load job em append na bronze (tudo STRING)

Por que `updated_on` e nao a data do crime: o portal publica com ~7 dias de
atraso e reclassifica registros antigos. Filtrar pela data do crime perderia
essas correcoes. A marca d'agua usa `>=`, entao a borda e relida de proposito;
quem deduplica e o MERGE da silver (idempotente).
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import functions_framework
import requests
from google.cloud import bigquery, storage

SODA_URL = "https://data.cityofchicago.org/resource/ijzp-q8t2.json"
PAGE_SIZE = 50_000
MAX_RETRIES = 5

# Colunas pedidas explicitamente: o schema da bronze fica estavel mesmo se o
# portal acrescentar campos. `location` fica de fora (duplica latitude/longitude).
SOURCE_COLUMNS = [
    "id", "case_number", "date", "block", "iucr", "primary_type", "description",
    "location_description", "arrest", "domestic", "beat", "district", "ward",
    "community_area", "fbi_code", "x_coordinate", "y_coordinate", "year",
    "updated_on", "latitude", "longitude",
]
META_COLUMNS = [
    bigquery.SchemaField("_ingested_at", "TIMESTAMP"),
    bigquery.SchemaField("_run_id", "STRING"),
    bigquery.SchemaField("_mode", "STRING"),
    bigquery.SchemaField("_source_file", "STRING"),
]
BRONZE_SCHEMA = [bigquery.SchemaField(c, "STRING") for c in SOURCE_COLUMNS] + META_COLUMNS

BUCKET = os.environ["BUCKET"]
BRONZE_TABLE = os.environ["BRONZE_TABLE"]          # projeto.dataset.tabela
RAW_PREFIX = os.environ.get("RAW_PREFIX", "bronze/chicago_crimes")
APP_TOKEN = os.environ.get("SODA_APP_TOKEN", "")

class _Log:
    """Log estruturado (JSON em stdout): o Cloud Logging le `severity` e `message`."""
    def _emit(self, severity, msg, *args):
        print(json.dumps({"severity": severity, "message": msg % args if args else msg,
                          "component": "ingest-chicago"}, ensure_ascii=False), flush=True)
    def info(self, msg, *args):
        self._emit("INFO", msg, *args)
    def warning(self, msg, *args):
        self._emit("WARNING", msg, *args)


log = _Log()

bq = bigquery.Client()
gcs = storage.Client()


def _as_string(value):
    """Bronze guarda tudo como texto, sem interpretar (a tipagem e da silver)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _fetch_page(session, where, offset):
    params = {
        "$select": ",".join(SOURCE_COLUMNS),
        "$where": where,
        "$order": ":id",          # ordem estavel para a paginacao por offset
        "$limit": PAGE_SIZE,
        "$offset": offset,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(SODA_URL, params=params, timeout=300)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            log.warning("pagina offset=%s falhou (%s); nova tentativa em %ss", offset, exc, wait)
            time.sleep(wait)
    return []


def _current_watermark():
    """Maior `updated_on` ja carregado. String ISO ordena igual a data."""
    try:
        rows = bq.query(f"SELECT MAX(updated_on) AS wm FROM `{BRONZE_TABLE}`").result()
        return next(iter(rows)).wm
    except Exception as exc:  # tabela ainda nao existe
        log.warning("nao foi possivel ler a marca d'agua: %s", exc)
        return None


def _load_to_bronze(uri_pattern):
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=BRONZE_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY, field="_ingested_at"),
        ignore_unknown_values=True,
    )
    job = bq.load_table_from_uri(uri_pattern, BRONZE_TABLE, job_config=job_config)
    job.result()
    return job.output_rows


@functions_framework.http
def ingest(request):
    mode = request.args.get("mode", "incremental")
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    if mode == "backfill":
        year = request.args.get("year", "")
        if not (year.isdigit() and 2001 <= int(year) <= now.year):
            return ({"erro": "informe ?year=AAAA entre 2001 e o ano atual"}, 400)
        where = f"year={int(year)}"
        watermark = None
    elif mode == "incremental":
        watermark = request.args.get("since") or _current_watermark()
        if not watermark:
            return ({"erro": "bronze vazia: rode o backfill antes do incremental"}, 409)
        where = f"updated_on >= '{watermark}'"
    else:
        return ({"erro": "mode deve ser incremental ou backfill"}, 400)

    prefix = f"{RAW_PREFIX}/ingestion_date={now:%Y-%m-%d}/run={run_id}"
    bucket = gcs.bucket(BUCKET)
    session = requests.Session()
    if APP_TOKEN:
        session.headers["X-App-Token"] = APP_TOKEN

    log.info("inicio run=%s mode=%s where=%s", run_id, mode, where)
    offset, page, total, max_updated = 0, 0, 0, None
    while True:
        records = _fetch_page(session, where, offset)
        if not records:
            break
        blob_name = f"{prefix}/part-{page:04d}.json"
        lines = []
        for rec in records:
            row = {c: _as_string(rec.get(c)) for c in SOURCE_COLUMNS}
            row.update({"_ingested_at": now.isoformat(), "_run_id": run_id,
                        "_mode": mode, "_source_file": f"gs://{BUCKET}/{blob_name}"})
            lines.append(json.dumps(row, ensure_ascii=False))
            if row["updated_on"] and (max_updated is None or row["updated_on"] > max_updated):
                max_updated = row["updated_on"]
        bucket.blob(blob_name).upload_from_string(
            "\n".join(lines) + "\n", content_type="application/x-ndjson")
        total += len(records)
        page += 1
        log.info("pagina %s: %s registros (total %s)", page, len(records), total)
        if len(records) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    loaded = _load_to_bronze(f"gs://{BUCKET}/{prefix}/part-*.json") if total else 0
    summary = {
        "run_id": run_id, "mode": mode, "where": where,
        "marca_dagua_usada": watermark, "maior_updated_on_lido": max_updated,
        "paginas": page, "registros_api": total, "linhas_carregadas": loaded,
        "raw": f"gs://{BUCKET}/{prefix}/", "tabela": BRONZE_TABLE,
    }
    log.info("fim %s", json.dumps(summary))
    return (summary, 200)
