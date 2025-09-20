
# routes/cnpj_publica.py
# MEI Robô — Integração CNPJ.ws (API Pública) v1
# Rota: GET /integracoes/cnpj/<cnpj>
# - Sem token (fonte pública), limite 3 req/min/IP na origem
# - Cache em memória (TTL padrão 24h) — substituível por Redis
# - Normaliza para o "esquema canônico" do MEI Robô
# - Heurística opcional por nome (?nome=...): EXATO | PROVAVEL | NAO_ENCONTRADO
#
# Dependências: Flask, requests
#   pip install Flask requests

import re
import time
import json
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple, Optional

from flask import Blueprint, request, jsonify, make_response

bp_cnpj_publica = Blueprint("cnpj_publica", __name__)

CNPJWS_PUBLIC_BASE = "https://publica.cnpj.ws"
HTTP_TIMEOUT = 8  # seconds
CACHE_TTL_SECS = 24 * 60 * 60  # 24h

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}  # key: cnpj, val: (expiry_ts, payload)


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _valid_cnpj14(s: str) -> bool:
    return bool(re.fullmatch(r"\d{14}", s or ""))


def _normalize_text(s: str) -> str:
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().upper()


def _match_nome(nome_busca: str, razao: str, socios: list) -> Tuple[str, Optional[str]]:
    """Retorna (avaliacao, origem) onde origem in {"RAZAO_SOCIAL","SOCIOS",None}"""
    if not nome_busca:
        return ("NAO_INFORMADO", None)
    nb = _normalize_text(nome_busca)
    if not nb:
        return ("NAO_INFORMADO", None)

    raz = _normalize_text(razao)
    if raz and nb == raz:
        return ("EXATO", "RAZAO_SOCIAL")
    if raz and nb in raz:
        return ("PROVAVEL", "RAZAO_SOCIAL")

    for s in socios or []:
        nome_s = _normalize_text(s.get("nome") or "")
        if not nome_s:
            continue
        if nb == nome_s:
            return ("EXATO", "SOCIOS")
        if nb in nome_s or nome_s in nb:
            return ("PROVAVEL", "SOCIOS")

    return ("NAO_ENCONTRADO", None)


def _map_canonic(json_src: Dict[str, Any]) -> Dict[str, Any]:
    """Mapeia JSON da CNPJ.ws pública para o esquema canônico do MEI Robô."""
    razao_social = json_src.get("razao_social")
    estabelecimento = json_src.get("estabelecimento") or {}
    simples = json_src.get("simples") or {}
    socios = json_src.get("socios") or []

    atividade_principal = estabelecimento.get("atividade_principal") or {}
    atividades_secundarias = estabelecimento.get("atividades_secundarias") or []

    endereco = {
        "logradouro": estabelecimento.get("logradouro"),
        "numero": estabelecimento.get("numero"),
        "bairro": estabelecimento.get("bairro"),
        "municipio": estabelecimento.get("cidade") or estabelecimento.get("municipio"),
        "uf": estabelecimento.get("estado") or estabelecimento.get("uf"),
        "cep": estabelecimento.get("cep"),
        "complemento": estabelecimento.get("complemento"),
    }

    socios_out = []
    for s in socios:
        socios_out.append({
            "nome": s.get("nome"),
            "qualificacao": s.get("qualificacao") or s.get("qualificacao_socio")
        })

    canonic = {
        "fonte": "cnpj.ws_publica",
        "cnpj": _only_digits(estabelecimento.get("cnpj") or json_src.get("cnpj_completo") or ""),
        "razaoSocial": razao_social,
        "nomeFantasia": estabelecimento.get("nome_fantasia"),
        "dataAbertura": estabelecimento.get("data_inicio_atividade"),
        "situacao": estabelecimento.get("situacao"),
        "cnaePrincipal": {
            "codigo": atividade_principal.get("codigo"),
            "descricao": atividade_principal.get("descricao"),
        },
        "cnaesSecundarios": [
            {"codigo": it.get("codigo"), "descricao": it.get("descricao")} for it in atividades_secundarias
        ],
        "endereco": endereco,
        "simples": {
            "optante": bool(simples.get("simples")) if isinstance(simples.get("simples"), bool) else None,
            "mei": bool(simples.get("mei")) if isinstance(simples.get("mei"), bool) else None,
            "dataOpcaoSimples": simples.get("data_opcao"),
            "dataOpcaoMei": simples.get("data_opcao_mei") or simples.get("data_opcao_simei"),
        },
        "socios": socios_out,
        "atualizadoEm": (json_src.get("atualizado_em") or json_src.get("criado_em")),
    }
    return canonic


def _get_cached(cnpj: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    item = _cache.get(cnpj)
    if not item:
        return None
    exp, payload = item
    if now > exp:
        _cache.pop(cnpj, None)
        return None
    return payload


def _set_cache(cnpj: str, payload: Dict[str, Any]):
    _cache[cnpj] = (time.time() + CACHE_TTL_SECS, payload)


@bp_cnpj_publica.route("/integracoes/cnpj/<cnpj>", methods=["GET"])
def integrar_cnpj_publica(cnpj: str):
    raw = cnpj or ""
    clean = _only_digits(raw)
    if not _valid_cnpj14(clean):
        return make_response(jsonify({"erro": "CNPJ inválido", "cnpj": clean}), 400)

    # cache
    cached = _get_cached(clean)
    if cached:
        resp = dict(cached)  # shallow copy
        # enriquecimento por nome (se solicitado) não é cacheado, para não poluir
        nome = request.args.get("nome", "", type=str)
        if nome:
            avaliacao, origem = _match_nome(nome, resp.get("razaoSocial"), resp.get("socios"))
            resp["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}
        return jsonify(resp)

    url = f"{CNPJWS_PUBLIC_BASE}/cnpj/{clean}"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        return make_response(jsonify({"erro": "Falha ao consultar origem", "detalhe": str(e)}), 502)

    # repassar alguns status da origem
    if r.status_code == 404:
        return make_response(jsonify({"erro": "CNPJ não encontrado", "cnpj": clean}), 404)
    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After")
        msg = {"erro": "Muitas consultas. Tente novamente em instantes.", "cnpj": clean}
        resp = make_response(jsonify(msg), 429)
        if retry_after:
            resp.headers["Retry-After"] = retry_after
        return resp
    if r.status_code >= 500:
        return make_response(jsonify({"erro": "Indisponibilidade na origem"}), 502)

    try:
        data = r.json()
    except ValueError:
        return make_response(jsonify({"erro": "Resposta inválida da origem"}), 502)

    canonic = _map_canonic(data)
    _set_cache(clean, canonic)

    # enriquecimento: heurística por nome se solicitado
    nome = request.args.get("nome", "", type=str)
    if nome:
        avaliacao, origem = _match_nome(nome, canonic.get("razaoSocial"), canonic.get("socios"))
        canonic["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}

    return jsonify(canonic)
