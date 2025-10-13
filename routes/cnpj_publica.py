# routes/cnpj_publica.py
# MEI Robô — Integração CNPJ.ws (API Pública) v1 (com heurística aprimorada)
# Rota: GET /integracoes/cnpj/<cnpj>
# - Sem token (fonte pública), limite 3 req/min/IP na origem
# - Cache em memória (TTL padrão 24h) — substituível por Redis
# - Normaliza para o "esquema canônico" do MEI Robô
# - Heurística por nome (?nome=...): EXATO | PROVAVEL | NAO_ENCONTRADO
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

# ====== CORS restrito somente para este blueprint ======
_ALLOWED_ORIGINS = {
    "https://www.meirobo.com.br",
    "https://meirobo.com.br",
    # Adicione seu preview se for testar a partir de um canal do Firebase Hosting:
    # "https://<preview>--mei-robo-prod.web.app",
}
_CORS_MAX_AGE = "86400"  # 24h

def _add_cors_headers(resp):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Max-Age"] = _CORS_MAX_AGE
        # Se não precisa enviar cookies/auth por cabeçalho, pode omitir a próxima linha.
        # Mantive compatível; remova se quiser estritamente sem credenciais.
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp
# =======================================================


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def _valid_cnpj14(s: str) -> bool:
    return bool(re.fullmatch(r"\d{14}", s or ""))


def _normalize_text(s: str) -> str:
    """
    Normaliza texto para comparação:
    - NFKD + remove acentos
    - Remove pontuações comuns (' . , - / \ ( ) [ ] { } " : ;)
    - Colapsa espaços
    - Uppercase
    """
    import unicodedata, re
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # Troca pontuação por espaço e remove caracteres não alfanuméricos (mantém letras/números/espaço)
    s = re.sub(r"[\'\".,\-_/\(\)\[\]\{\}:;]+", " ", s)
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _match_nome(nome_busca: str, razao: str, socios: list) -> Tuple[str, Optional[str]]:
    if not nome_busca:
        return ("NAO_INFORMADO", None)

    def tokens(s: str):
        stops = {"DA", "DE", "DO", "DAS", "DOS", "D", "E"}
        base = _normalize_text(s)
        toks = [t for t in base.split() if t and t not in stops]
        return base, toks

    base_busca, toks_busca = tokens(nome_busca)
    if not toks_busca and not base_busca:
        return ("NAO_INFORMADO", None)

    def eval_alvo(alvo: str) -> Tuple[str, Optional[str]]:
        base_alvo, toks_alvo = tokens(alvo or "")
        if not base_alvo:
            return ("NAO_ENCONTRADO", None)
        # EXATO
        if base_busca == base_alvo:
            return ("EXATO", None)
        # Substring direta
        if base_busca and base_busca in base_alvo:
            return ("PROVAVEL", None)
        # Tokens em ordem (>=2)
        if toks_busca:
            i = 0
            hits = 0
            for t in toks_alvo:
                if i < len(toks_busca) and t == toks_busca[i]:
                    hits += 1
                    i += 1
                    if hits >= 2:
                        return ("PROVAVEL", None)
        # Token forte (>=4 chars) presente
        for tb in toks_busca:
            if len(tb) >= 4 and tb in base_alvo.split():
                return ("PROVAVEL", None)
        return ("NAO_ENCONTRADO", None)

    # Razão Social
    aval, _ = eval_alvo(razao)
    if aval == "EXATO":
        return ("EXATO", "RAZAO_SOCIAL")
    if aval == "PROVAVEL":
        return ("PROVAVEL", "RAZAO_SOCIAL")

    # Sócios
    for s in socios or []:
        aval_s, _ = eval_alvo(s.get("nome") or "")
        if aval_s == "EXATO":
            return ("EXATO", "SOCIOS")
        if aval_s == "PROVAVEL":
            return ("PROVAVEL", "SOCIOS")

    return ("NAO_ENCONTRADO", None)


def _map_canonic(json_src: Dict[str, Any]) -> Dict[str, Any]]:
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


@bp_cnpj_publica.route("/integracoes/cnpj/<cnpj>", methods=["GET", "OPTIONS"])
def integrar_cnpj_publica(cnpj: str):
    # Pré-flight CORS
    if request.method == "OPTIONS":
        return _add_cors_headers(make_response("", 204))

    raw = cnpj or ""
    clean = _only_digits(raw)
    if not _valid_cnpj14(clean):
        return _add_cors_headers(make_response(jsonify({"erro": "CNPJ inválido", "cnpj": clean}), 400))

    # cache
    cached = _get_cached(clean)
    if cached:
        resp = dict(cached)  # shallow copy
        # enriquecimento por nome (se solicitado) não é cacheado, para não poluir
        nome = request.args.get("nome", "", type=str)
        if nome:
            avaliacao, origem = _match_nome(nome, resp.get("razaoSocial"), resp.get("socios"))
            resp["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}
        return _add_cors_headers(jsonify(resp))

    url = f"{CNPJWS_PUBLIC_BASE}/cnpj/{clean}"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        return _add_cors_headers(make_response(jsonify({"erro": "Falha ao consultar origem", "detalhe": str(e)}), 502))

    # repassar alguns status da origem
    if r.status_code == 404:
        return _add_cors_headers(make_response(jsonify({"erro": "CNPJ não encontrado", "cnpj": clean}), 404))
    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After")
        msg = {"erro": "Muitas consultas. Tente novamente em instantes.", "cnpj": clean}
        resp = make_response(jsonify(msg), 429)
        if retry_after:
            resp.headers["Retry-After"] = retry_after
        return _add_cors_headers(resp)
    if r.status_code >= 500:
        return _add_cors_headers(make_response(jsonify({"erro": "Indisponibilidade na origem"}), 502))

    try:
        data = r.json()
    except ValueError:
        return _add_cors_headers(make_response(jsonify({"erro": "Resposta inválida da origem"}), 502))

    canonic = _map_canonic(data)
    _set_cache(clean, canonic)

    # enriquecimento: heurística por nome se solicitado
    nome = request.args.get("nome", "", type=str)
    if nome:
        avaliacao, origem = _match_nome(nome, canonic.get("razaoSocial"), canonic.get("socios"))
        canonic["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}

    return _add_cors_headers(jsonify(canonic))


@bp_cnpj_publica.after_request
def _after_request(resp):
    # Garante CORS nas respostas do blueprint
    return _add_cors_headers(resp)
