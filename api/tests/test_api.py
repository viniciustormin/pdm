"""Testes da API."""
from __future__ import annotations

from datetime import datetime

import pytest


# --------------------------------------------------------------------- infra
def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "ok"
    assert corpo["modelo_carregado"] is True
    assert corpo["janelas_carregadas"] == 4


def test_model_info_traz_contrato(client):
    r = client.get("/model-info")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["alvo"] == "houve_prisao"
    assert corpo["features"][:3] == ["tipo_crime", "local_ocorrencia", "distrito_policial"]
    assert corpo["janelas"]["distritos"] == [12, 19]
    # O contrato veio do arquivo, não do padrão embutido no código.
    assert corpo["janelas"]["contrato_do_padrao"] is False


# ------------------------------------------------------------------ predicao
def test_predict_devolve_probabilidade_valida(client, ocorrencia_base):
    r = client.post("/predict", json=ocorrencia_base)
    assert r.status_code == 200
    corpo = r.json()
    assert 0.0 <= corpo["prob_prisao"] <= 1.0
    assert corpo["predicao"] is (corpo["prob_prisao"] >= corpo["limiar"])
    assert corpo["latencia_ms"] > 0
    assert corpo["versao_modelo"]


def test_predict_header_de_latencia(client, ocorrencia_base):
    r = client.post("/predict", json=ocorrencia_base)
    assert "X-Latencia-Ms" in r.headers
    assert float(r.headers["X-Latencia-Ms"]) > 0


def test_unique_key_volta_na_resposta(client, ocorrencia_base):
    r = client.post("/predict", json={**ocorrencia_base, "unique_key": "abc-123"})
    assert r.json()["unique_key"] == "abc-123"


# ---------------------------------------------------------------- teve_jogo
def test_teve_jogo_consultado_dentro_da_janela(client, ocorrencia_base):
    """19h no distrito 19 em 04/07 cai dentro de j1 (17h-20h)."""
    r = client.post("/predict", json=ocorrencia_base)
    corpo = r.json()
    assert corpo["teve_jogo"] is True
    assert corpo["teve_jogo_origem"] == "consultado"
    assert corpo["id_janela"] in {"j1", "j2"}


def test_teve_jogo_false_fora_da_janela(client, ocorrencia_base):
    oc = {**ocorrencia_base, "data_hora_local_chicago": "2026-07-04T23:00:00"}
    corpo = client.post("/predict", json=oc).json()
    assert corpo["teve_jogo"] is False
    assert corpo["id_janela"] is None


def test_janela_sobreposta_resolve(client, ocorrencia_base):
    """21h cai só em j2 (18h30-21h30), já fora de j1.

    Sem o prefixo de máximo do fim, a busca binária pararia em j2 e daria
    certo por acaso; o caso que realmente quebra é o de baixo.
    """
    oc = {**ocorrencia_base, "data_hora_local_chicago": "2026-07-04T21:00:00"}
    corpo = client.post("/predict", json=oc).json()
    assert corpo["teve_jogo"] is True
    assert corpo["id_janela"] == "j2"


def test_janela_que_vira_o_dia(client, ocorrencia_base):
    """j3 vai de 11/07 22h até 12/07 01h. 00h30 do dia 12 está dentro."""
    oc = {**ocorrencia_base, "data_hora_local_chicago": "2026-07-12T00:30:00"}
    assert client.post("/predict", json=oc).json()["teve_jogo"] is True


def test_borda_fechada_no_inicio_aberta_no_fim(client, ocorrencia_base):
    """Mesma convenção da gold: ini <= t < fim."""
    dentro = {**ocorrencia_base, "data_hora_local_chicago": "2026-03-15T23:00:00",
              "distrito_policial": 12}
    fora = {**ocorrencia_base, "data_hora_local_chicago": "2026-03-16T02:00:00",
            "distrito_policial": 12}
    assert client.post("/predict", json=dentro).json()["teve_jogo"] is True
    assert client.post("/predict", json=fora).json()["teve_jogo"] is False


def test_override_tem_precedencia_sobre_consulta(client, ocorrencia_base):
    oc = {**ocorrencia_base, "teve_jogo": False}  # dentro da janela, mas forçado
    corpo = client.post("/predict", json=oc).json()
    assert corpo["teve_jogo"] is False
    assert corpo["teve_jogo_origem"] == "informado"


def test_distrito_sem_estadio_nunca_tem_jogo(client, ocorrencia_base):
    oc = {**ocorrencia_base, "distrito_policial": 7}
    assert client.post("/predict", json=oc).json()["teve_jogo"] is False


# ------------------------------------------------------------------- features
def test_dia_semana_segue_convencao_do_bigquery():
    """1 = domingo ... 7 = sábado, igual ao EXTRACT(DAYOFWEEK).

    Este é o teste que impede o erro mais caro da integração: se a API
    calcular o dia da semana numa convenção e o treino em outra, a predição
    sai errada sem lançar exceção nenhuma.
    """
    from app.features import dia_semana_bq

    esperado = {
        datetime(2026, 7, 5): 1,   # domingo
        datetime(2026, 7, 6): 2,   # segunda
        datetime(2026, 7, 7): 3,
        datetime(2026, 7, 8): 4,
        datetime(2026, 7, 9): 5,
        datetime(2026, 7, 10): 6,
        datetime(2026, 7, 11): 7,  # sábado
    }
    for data, valor in esperado.items():
        assert dia_semana_bq(data) == valor, data


def test_horario_com_offset_e_convertido_para_chicago():
    from app.features import normalizar_para_chicago

    # 2026-07-05T03:00:00Z = 2026-07-04 22:00 em Chicago (CDT, UTC-5)
    com_offset = datetime.fromisoformat("2026-07-05T03:00:00+00:00")
    assert normalizar_para_chicago(com_offset).hour == 22


def test_horario_sem_offset_e_tratado_como_chicago():
    from app.features import normalizar_para_chicago

    naive = datetime(2026, 7, 4, 19, 0)
    assert normalizar_para_chicago(naive) == naive


# ------------------------------------------------------------------ validacao
@pytest.mark.parametrize(
    "mudanca",
    [
        {"tipo_crime": ""},                       # vazio
        {"distrito_policial": 0},                 # fora da faixa
        {"distrito_policial": 99},                # fora da faixa
        {"distrito_policial": "dezenove"},        # tipo errado
        {"data_hora_local_chicago": "ontem"},     # data inválida
        {"eh_domestico": "talvez"},               # bool inválido
    ],
)
def test_entrada_invalida_devolve_422(client, ocorrencia_base, mudanca):
    r = client.post("/predict", json={**ocorrencia_base, **mudanca})
    assert r.status_code == 422


def test_campo_obrigatorio_ausente_devolve_422(client, ocorrencia_base):
    oc = dict(ocorrencia_base)
    del oc["tipo_crime"]
    assert client.post("/predict", json=oc).status_code == 422


def test_campo_extra_e_ignorado(client, ocorrencia_base):
    """O producer pode evoluir o evento; campo novo não pode derrubar a API."""
    r = client.post("/predict", json={**ocorrencia_base, "campo_novo": 123})
    assert r.status_code == 200


def test_tipo_de_crime_desconhecido_nao_quebra(client, ocorrencia_base):
    """OneHotEncoder com handle_unknown='ignore' tem que absorver categoria nova."""
    oc = {**ocorrencia_base, "tipo_crime": "CRIME QUE NAO EXISTE"}
    r = client.post("/predict", json=oc)
    assert r.status_code == 200
    assert 0.0 <= r.json()["prob_prisao"] <= 1.0


# ----------------------------------------------------------------------- lote
def test_batch_devolve_uma_predicao_por_item(client, ocorrencia_base):
    lote = {"ocorrencias": [ocorrencia_base for _ in range(5)]}
    r = client.post("/predict/batch", json=lote)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == 5
    assert len(corpo["predicoes"]) == 5
    assert corpo["latencia_media_ms"] <= corpo["latencia_ms"]


def test_batch_vazio_devolve_422(client):
    assert client.post("/predict/batch", json={"ocorrencias": []}).status_code == 422


def test_batch_preserva_ordem(client, ocorrencia_base):
    itens = [
        {**ocorrencia_base, "unique_key": f"k{i}", "tipo_crime": t}
        for i, t in enumerate(["THEFT", "NARCOTICS", "BATTERY"])
    ]
    corpo = client.post("/predict/batch", json={"ocorrencias": itens}).json()
    assert [p["unique_key"] for p in corpo["predicoes"]] == ["k0", "k1", "k2"]


def test_batch_e_predict_concordam(client, ocorrencia_base):
    """Mesma entrada, mesmo número — garante que o caminho vetorizado do lote
    não diverge do caminho de item único."""
    um = client.post("/predict", json=ocorrencia_base).json()["prob_prisao"]
    lote = client.post("/predict/batch", json={"ocorrencias": [ocorrencia_base]}).json()
    assert lote["predicoes"][0]["prob_prisao"] == pytest.approx(um, abs=1e-9)
