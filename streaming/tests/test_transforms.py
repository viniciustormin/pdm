import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from transforms import EventoInvalido, limpar_evento  # noqa: E402

DIM = {313: 3}
BASE = {"event_id": "e1", "id": "SIM-1", "date": "2026-10-23T21:14:05",
        "primary_type": " theft ", "description": "$500 AND UNDER",
        "location_description": "street", "domestic": False, "beat": "0313",
        "district": "003", "latitude": 41.78, "longitude": -87.60,
        "published_at": "2026-10-24T02:14:05Z"}


def evento(**mudancas):
    e = dict(BASE)
    e.update(mudancas)
    return json.dumps(e)


def test_evento_valido_e_tipado():
    r = limpar_evento(evento(), DIM)
    assert r["distrito_policial"] == 3 and r["beat"] == 313
    assert r["tipo_crime"] == "THEFT" and r["local_ocorrencia"] == "STREET"
    assert r["data_ocorrencia"] == "2026-10-23" and r["hora_ocorrencia"] == 21
    assert r["data_hora_local_chicago"] == "2026-10-23 21:14:05"   # sem conversao de fuso


def test_recupera_distrito_pelo_beat():
    assert limpar_evento(evento(district=None), DIM)["distrito_policial"] == 3


def test_coordenada_fora_de_chicago_vira_nulo():
    r = limpar_evento(evento(latitude=0.0, longitude=0.0), DIM)
    assert r["latitude"] is None and r["longitude"] is None


@pytest.mark.parametrize("payload, trecho", [
    ("{quebrado", "JSON invalido"),
    (evento(district="099"), "distrito invalido"),
    (evento(district=None, beat=None), "distrito invalido"),
    (evento(date="23/10/2026"), "date em formato invalido"),
    (evento(primary_type=""), "campos obrigatorios"),
])
def test_eventos_invalidos(payload, trecho):
    with pytest.raises(EventoInvalido, match=trecho):
        limpar_evento(payload, DIM)
