# routes/cnpj_publica.py
# MEI Robô — Integração CNPJ.ws (API Pública) v1 (com heurística aprimorada)
# Endpoints:
#   - GET /api/cnpj/<cnpj>                (novo)
#   - GET /integracoes/cnpj/<cnpj>        (legado mantido)
#
# - Sem token (fonte pública), limite X req/min/IP (env)
# - Cache em memória (TTL padrão 24h) — substituível por Redis
# - Normaliza para o "esquema canônico" do MEI Robô
# - Heurística por nome (?nome=...): EXATO | PROVAVEL | NAO_ENCONTRADO

import os
import re
import time
import json
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, Tuple, Optional, List

from flask import Blueprint, request, jsonify, make_response, current_app

# ──────────────────────────────────────────────────────────────────────────────
# Blueprint (sem prefixo global) — expõe /api/cnpj e /integracoes/cnpj
# ──────────────────────────────────────────────────────────────────────────────
cnpj_bp = Blueprint("cnpj_publica", __name__)
bp_cnpj_publica = cnpj_bp  # compat nome legado

# ======================== Config por ENV =========================
CNPJWS_PUBLIC_BASE = os.getenv("CNPJWS_PUBLIC_BASE", "https://publica.cnpj.ws").rstrip("/")
HTTP_TIMEOUT = 8  # seconds
CACHE_TTL_SECS = int(os.getenv("CNPJ_CACHE_TTL_SECS", str(24 * 60 * 60)))  # 24h
CACHE_MAX = int(os.getenv("CNPJ_CACHE_MAX_ENTRIES", "2000"))               # soft limit
_RATE_LIMIT_MAX = int(os.getenv("CNPJ_RATE_MAX_PER_MIN", "10"))

# CORS allow-list (padrão + extras do env, separados por vírgula)
_ALLOWED_ORIGINS = {
    "https://www.meirobo.com.br",
    "https://meirobo.com.br",
}
_extra = [o.strip() for o in os.getenv("CNPJ_ALLOWED_ORIGINS", "").split(",") if o.strip()]
_ALLOWED_ORIGINS.update(_extra)
_CORS_MAX_AGE = "86400"  # 24h

# ======================== Cache in-memory ========================
_cache: Dict[str, Tuple[float, Dict[str, Any], str]] = {}  # key: cnpj → (expiry_ts, payload, etag)

def _json_etag(payload: Dict[str, Any]) -> str:
    """ETag determinística baseada no JSON indentado com chaves ordenadas."""
    try:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:32]
    except Exception:
        # fallback fraco, mas não quebra
        return str(hash(str(payload)))[:16]

def _get_cached(cnpj: str) -> Optional[Tuple[Dict[str, Any], str]]:
    now = time.time()
    item = _cache.get(cnpj)
    if not item:
        return None
    exp, payload, etag = item
    if now > exp:
        _cache.pop(cnpj, None)
        return None
    return payload, etag

def _set_cache(cnpj: str, payload: Dict[str, Any]):
    # Trim simples se extrapolar o limite (descarta itens mais antigos por expiração aproximada)
    if CACHE_MAX > 0 and len(_cache) >= CACHE_MAX:
        try:
            # remove os 5% mais antigos (aprox.) para aliviar pressão
            to_remove = max(1, CACHE_MAX // 20)
            oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:to_remove]
            for k, _ in oldest:
                _cache.pop(k, None)
        except Exception:
            pass
    etag = _json_etag(payload)
    _cache[cnpj] = (time.time() + CACHE_TTL_SECS, payload, etag)

# ======================== CORS por blueprint =====================
def _add_cors_headers(resp):
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, If-None-Match"
        resp.headers["Access-Control-Max-Age"] = _CORS_MAX_AGE
        # Sem cookies/auth, mas mantido true para flexibilidade
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp

# ======================== Rate limit simples =====================
_rate_bucket: Dict[str, Tuple[int, int]] = {}  # ip -> (window_minute, count)

def _client_ip() -> str:
    return (
        request.headers.get("CF-Connecting-IP")
        or (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() if request.headers.get("X-Forwarded-For") else "")
        or request.remote_addr
        or "0.0.0.0"
    )

def _rate_limit_ok(ip: str) -> bool:
    if _RATE_LIMIT_MAX <= 0:
        return True
    now_min = int(time.time() // 60)
    win, cnt = _rate_bucket.get(ip, (now_min, 0))
    if win != now_min:
        win, cnt = now_min, 0
    cnt += 1
    _rate_bucket[ip] = (win, cnt)
    return cnt <= _RATE_LIMIT_MAX

# ======================== Normalização/Heurística ================
def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def _valid_cnpj14(s: str) -> bool:
    return bool(re.fullmatch(r"\d{14}", s or ""))

def _normalize_text(s: str) -> str:
    """
    Normaliza texto para comparação:
    - NFKD + remove acentos
    - Remove pontuações
    - Colapsa espaços
    - Uppercase
    """
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[\'\".,\-_/\(\)\[\]\{\}:;]+", " ", s)
    s = re.sub(r"[^A-Za-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s

# --- Fallback de CNAE: extrai código da descrição, se necessário ---
_CNAE_CODE_RE = re.compile(r"(\d{2}\.\d{2}-\d)(?:/\d{1,2})?")

def _cnae_from_any(obj: dict) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(obj, dict):
        return (None, None)

    cand_code = obj.get("codigo") or obj.get("code") or obj.get("id") or obj.get("cnae")
    cand_desc = obj.get("descricao") or obj.get("description") or obj.get("text")

    if cand_code:
        cand_code = str(cand_code).strip()
        # Normaliza: 1234-5 → 12.34-5
        if re.fullmatch(r"\d{4}-\d", cand_code):
            cand_code = cand_code[:2] + "." + cand_code[2:]
    else:
        if isinstance(cand_desc, str):
            m = _CNAE_CODE_RE.search(cand_desc)
            if m:
                cand_code = m.group(1)

    return (cand_code or None, cand_desc or None)

def _match_nome(nome_busca: str, razao: str, socios: List[dict]) -> Tuple[str, Optional[str]]:
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

    # CNAE com fallback
    cnae_pri_code, cnae_pri_desc = _cnae_from_any(atividade_principal)
    cnaes_sec_list = []
    for it in atividades_secundarias:
        code, desc = _cnae_from_any(it or {})
        cnaes_sec_list.append({"codigo": code, "descricao": desc})

    canonic = {
        "fonte": "cnpj.ws_publica",
        "cnpj": _only_digits(estabelecimento.get("cnpj") or json_src.get("cnpj_completo") or ""),
        "razaoSocial": razao_social,
        "nomeFantasia": estabelecimento.get("nome_fantasia"),
        "dataAbertura": estabelecimento.get("data_inicio_atividade"),
        "situacao": estabelecimento.get("situacao"),
        "cnaePrincipal": {"codigo": cnae_pri_code, "descricao": cnae_pri_desc},
        "cnaesSecundarios": cnaes_sec_list,
        "endereco": endereco,
        "simples": {
            "optante": simples.get("simples") if isinstance(simples.get("simples"), bool) else None,
            "mei": simples.get("mei") if isinstance(simples.get("mei"), bool) else None,
            "dataOpcaoSimples": simples.get("data_opcao"),
            "dataOpcaoMei": simples.get("data_opcao_mei") or simples.get("data_opcao_simei"),
        },
        "socios": socios_out,
        "atualizadoEm": (json_src.get("atualizado_em") or json_src.get("criado_em")),
    }
    return canonic

# ======================== HTTP helpers ===========================
def _requests_get_with_retries(url: str, *, timeout: int, max_retries: int = 2):
    last_exc = None
    for i in range(max_retries + 1):
        try:
            return requests.get(url, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            # backoff curto
            time.sleep(0.25 * (i + 1))
    raise last_exc or requests.RequestException("request_failed")

# ======================== Core handlers ==========================
def _handle_cnpj_lookup(clean: str):
    # cache
    cached = _get_cached(clean)
    if cached:
        payload, etag = cached

        # If-None-Match → 304
        inm = request.headers.get("If-None-Match")
        if inm and inm.strip('"') == etag:
            resp = make_response("", 304)
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "public, max-age=3600"
            resp.headers["X-Cache-Status"] = "HIT"
            return _add_cors_headers(resp)

        # enriquecer com vinculoNome, se solicitado
        resp_payload = dict(payload)
        nome = request.args.get("nome", "", type=str)
        if nome:
            avaliacao, origem = _match_nome(nome, resp_payload.get("razaoSocial"), resp_payload.get("socios"))
            resp_payload["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}

        out = jsonify(resp_payload)
        out.headers["X-Cache-Status"] = "HIT"
        out.headers["ETag"] = etag
        out.headers.setdefault("Cache-Control", "public, max-age=3600")
        return _add_cors_headers(out)

    # origem
    url = f"{CNPJWS_PUBLIC_BASE}/cnpj/{clean}"
    try:
        r = _requests_get_with_retries(url, timeout=HTTP_TIMEOUT, max_retries=2)
    except requests.RequestException as e:
        current_app.logger.info({"event": "cnpj.fetch_error", "cnpj": clean, "detail": str(e)})
        return _add_cors_headers(make_response(jsonify({"erro": "Falha ao consultar origem"}), 502))

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
    etag = _json_etag(canonic)

    # If-None-Match para MISS recém-populada
    inm = request.headers.get("If-None-Match")
    if inm and inm.strip('"') == etag:
        resp = make_response("", 304)
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "public, max-age=3600"
        resp.headers["X-Cache-Status"] = "MISS-304"
        return _add_cors_headers(resp)

    # enriquecimento: heurística por nome se solicitado
    nome = request.args.get("nome", "", type=str)
    if nome:
        avaliacao, origem = _match_nome(nome, canonic.get("razaoSocial"), canonic.get("socios"))
        canonic["vinculoNome"] = {"entrada": nome, "avaliacao": avaliacao, "origem": origem}

    out = jsonify(canonic)
    out.headers["X-Cache-Status"] = "MISS"
    out.headers["ETag"] = etag
    out.headers.setdefault("Cache-Control", "public, max-age=3600")
    return _add_cors_headers(out)

# ── NOVO: /api/cnpj/<cnpj>
@cnpj_bp.route("/api/cnpj/<cnpj>", methods=["GET", "OPTIONS"])
def api_cnpj(cnpj: str):
    if request.method == "OPTIONS":
        return _add_cors_headers(make_response("", 204))

    # rate limit
    ip = _client_ip()
    if not _rate_limit_ok(ip):
        msg = {"erro": "too_many_requests", "retry": 60}
        return _add_cors_headers(make_response(jsonify(msg), 429))

    raw = cnpj or ""
    clean = _only_digits(raw)
    if not _valid_cnpj14(clean):
        return _add_cors_headers(make_response(jsonify({"erro": "CNPJ inválido", "cnpj": clean}), 400))
    return _handle_cnpj_lookup(clean)

# ── LEGADO: /integracoes/cnpj/<cnpj>
@cnpj_bp.route("/integracoes/cnpj/<cnpj>", methods=["GET", "OPTIONS"])
def integrar_cnpj_publica(cnpj: str):
    if request.method == "OPTIONS":
        return _add_cors_headers(make_response("", 204))

    # rate limit
    ip = _client_ip()
    if not _rate_limit_ok(ip):
        msg = {"erro": "too_many_requests", "retry": 60}
        return _add_cors_headers(make_response(jsonify(msg), 429))

    raw = cnpj or ""
    clean = _only_digits(raw)
    if not _valid_cnpj14(clean):
        return _add_cors_headers(make_response(jsonify({"erro": "CNPJ inválido", "cnpj": clean}), 400))
    return _handle_cnpj_lookup(clean)

@cnpj_bp.after_request
def _after_request(resp):
    # CORS deste blueprint
    resp = _add_cors_headers(resp)

    # Garante cabeçalhos de cache/etag em respostas JSON 200
    try:
        if resp.status_code == 200 and (resp.mimetype or "").startswith("application/json"):
            resp.headers.setdefault("Cache-Control", "public, max-age=3600")
            resp.headers.setdefault("ETag", resp.headers.get("ETag") or "")
    except Exception:
        pass
    return resp
