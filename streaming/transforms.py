"""Regras de limpeza do streaming: as mesmas da silver batch (sql/02_fn_crimes_silver.sql).

Funcoes puras, sem Beam, para poderem ser testadas isoladamente (tests/).
"""
import json
from datetime import datetime, timezone

# Caixa delimitadora aproximada da cidade de Chicago (mesma da silver)
LAT_MIN, LAT_MAX = 41.64, 42.03
LON_MIN, LON_MAX = -87.95, -87.52
DISTRITO_MIN, DISTRITO_MAX = 1, 25
CAMPOS_OBRIGATORIOS = ("event_id", "id", "date", "primary_type")


class EventoInvalido(ValueError):
    """Evento que nao pode ir para a tabela de stream; vai para a de erros."""


def _int_ou_none(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _float_ou_none(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _texto(valor):
    if valor is None:
        return None
    texto = " ".join(str(valor).split()).upper()
    return texto or None


def _bool(valor):
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.strip().lower() in ("true", "false"):
        return valor.strip().lower() == "true"
    return None


def _parse_data(valor):
    """Hora de parede de Chicago, sem fuso. Mantem a convencao do T1:
    grava como TIMESTAMP sem conversao (a gold le com TZ='UTC')."""
    if not isinstance(valor, str):
        raise EventoInvalido("date ausente ou nao textual")
    texto = valor.strip().rstrip("Z")
    for formato in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise EventoInvalido(f"date em formato invalido: {valor!r}")


def limpar_evento(payload, beat_para_distrito, agora=None):
    """Recebe o JSON bruto (bytes ou str) e devolve a linha de tb_crimes_stream.

    Levanta EventoInvalido com o motivo quando o evento nao passa nas regras.
    """
    agora = agora or datetime.now(timezone.utc)
    try:
        evento = json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise EventoInvalido(f"JSON invalido: {exc}") from exc
    if not isinstance(evento, dict):
        raise EventoInvalido("JSON nao e um objeto")

    faltando = [c for c in CAMPOS_OBRIGATORIOS if evento.get(c) in (None, "")]
    if faltando:
        raise EventoInvalido(f"campos obrigatorios ausentes: {', '.join(faltando)}")

    data_hora = _parse_data(evento["date"])
    beat = _int_ou_none(evento.get("beat"))
    distrito = _int_ou_none(evento.get("district"))
    if distrito is None and beat is not None:
        distrito = beat_para_distrito.get(beat)        # recupera pelo beat, como na silver
    if distrito is None or not DISTRITO_MIN <= distrito <= DISTRITO_MAX:
        raise EventoInvalido(f"distrito invalido: {evento.get('district')!r} (beat {evento.get('beat')!r})")

    lat = _float_ou_none(evento.get("latitude"))
    lon = _float_ou_none(evento.get("longitude"))
    dentro = lat is not None and lon is not None and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX

    publicado = evento.get("published_at")
    try:
        publicado_em = datetime.fromisoformat(publicado.replace("Z", "+00:00")) if publicado else None
    except ValueError:
        publicado_em = None

    return {
        "unique_key": str(evento["id"]),
        "event_id": str(evento["event_id"]),
        "data_hora_local_chicago": data_hora.strftime("%Y-%m-%d %H:%M:%S"),
        "data_ocorrencia": data_hora.strftime("%Y-%m-%d"),
        "hora_ocorrencia": data_hora.hour,
        "distrito_policial": distrito,
        "beat": beat,
        "tipo_crime": _texto(evento.get("primary_type")),
        "descricao_crime": _texto(evento.get("description")),
        "local_ocorrencia": _texto(evento.get("location_description")),
        "eh_domestico": _bool(evento.get("domestic")),
        "latitude": lat if dentro else None,
        "longitude": lon if dentro else None,
        "teve_jogo": None,          # preenchido no Trabalho Final
        "prob_prisao": None,        # preenchido no Trabalho Final (chamada a API)
        "_publicado_em": publicado_em.isoformat() if publicado_em else None,
        "_processado_em": agora.isoformat(),
    }


def linha_de_erro(payload, motivo, agora=None):
    agora = agora or datetime.now(timezone.utc)
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    return {"_recebido_em": agora.isoformat(), "motivo": motivo, "payload": payload}
