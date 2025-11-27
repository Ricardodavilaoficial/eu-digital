# routes/conta_status.py
from flask import Blueprint, jsonify, make_response, request, g
import os
import logging

bp_conta = Blueprint("bp_conta", __name__)

# Tentamos usar Firestore e auth padrão do projeto; se não tiver, caímos em fallback
try:
    from services.db import db  # type: ignore
except Exception:  # pragma: no cover
    db = None  # type: ignore

try:
    from services.auth import get_uid_from_bearer  # type: ignore
except Exception:  # pragma: no cover
    get_uid_from_bearer = None  # type: ignore


# -------- helpers seguros --------
def _env_int(name: str, default: int) -> int:
    """Lê int de ENV com fallback seguro (sem quebrar o boot)."""
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


def _snapshot_empresa():
    """
    Snapshot mínimo pro pós-pagamento (ativar-config).
    Pode trocar depois pra buscar do Firestore/receita/etc.
    Também aceita ENV para facilitar testes.
    """
    return {
        "cnpj": os.getenv("SNAP_CNPJ", "00000000000000"),
        "razaoSocial": os.getenv("SNAP_RAZAO", "Nome Ltda"),
        "nomeFantasia": os.getenv("SNAP_FANTASIA", "Nome"),
        "endereco": {
            "municipio": os.getenv("SNAP_MUNICIPIO", "Cidade"),
            "uf": os.getenv("SNAP_UF", "UF"),
        },
        "cnaePrincipal": {
            "codigo": os.getenv("SNAP_CNAE_COD", "9602-5/01"),
            "descricao": os.getenv("SNAP_CNAE_DESC", "Cabeleireiros..."),
        },
    }


# ============================================================
# 1) NOVO BLOCO — PERFIL PÚBLICO DEFAULT
# ============================================================
def _snapshot_publico_default():
    """
    Perfil público do MEI (o que aparece para os clientes).
    Pode ser overrideado pelo Firestore.
    """
    return {
        "nomePublico": os.getenv("SNAP_PUBLIC_NAME", "Seu negócio"),
        "segmentoPublico": os.getenv("SNAP_PUBLIC_SEGMENTO", "Profissional MEI"),
        "descricaoPublica": os.getenv("SNAP_PUBLIC_DESC", ""),
    }


# ============================================================
# 2) NOVO BLOCO — PERFIL PÚBLICO DO FIRESTORE
# ============================================================
def _snapshot_publico_from_firestore(uid: str | None):
    """
    Lê do Firestore o perfil público (nome que aparece para os clientes).
    Procura primeiro em profissionais/{uid}/config/* e também no doc principal
    profissionais/{uid}, dando prioridade ao que o MEI escolheu (especialidades).
    Se não achar nada, cai no default.
    """
    base_env = _snapshot_publico_default()

    if not uid or db is None:
        return base_env

    try:
        # ----- 1) Tenta ler config/comunicacao ou config/conta -----
        data_cfg = None
        try:
            col_cfg = (
                db.collection("profissionais")
                  .document(uid)
                  .collection("config")
            )
            doc = col_cfg.document("comunicacao").get()
            data_cfg = doc.to_dict() if doc.exists else None

            if not data_cfg:
                doc2 = col_cfg.document("conta").get()
                data_cfg = doc2.to_dict() if doc2.exists else None
        except Exception:
            logging.exception("conta_status: erro ao ler config/* para uid=%s", uid)
            data_cfg = None

        # ----- 2) Lê doc principal profissionais/{uid} -----
        data_prof = None
        try:
            doc_prof = (
                db.collection("profissionais")
                  .document(uid)
                  .get()
            )
            data_prof = doc_prof.to_dict() if doc_prof.exists else None
        except Exception:
            logging.exception("conta_status: erro ao ler profissionais/%s", uid)
            data_prof = None

        if not data_cfg and not data_prof:
            # Nada específico → volta pro default
            return base_env

        # Mapas auxiliares do doc principal
        branding = {}
        estilo = {}
        perfil = {}

        if isinstance(data_prof, dict):
            branding = data_prof.get("branding") or {}
            if not isinstance(branding, dict):
                branding = {}

            estilo = data_prof.get("estiloComunicacao") or {}
            if not isinstance(estilo, dict):
                estilo = {}

            perfil = data_prof.get("perfilProfissional") or {}
            if not isinstance(perfil, dict):
                perfil = {}

        # Dados de config (se existirem)
        data = data_cfg or {}

        # ----- nomePublico -----
        nome_publico = (
            data.get("nomePublico")
            or data.get("nome_publico")
            or data.get("displayName")
            or data.get("nomeNegocio")
            or data.get("nome_negocio")
            or branding.get("public_brand")
            or estilo.get("display_name")
            or base_env["nomePublico"]
        )

        # ----- segmentoPublico (especialidades primeiro) -----
        segmento_publico = (
            data.get("segmentoPublico")
            or data.get("segmento_publico")
            or data.get("nicho")
            or data.get("atividade")
        )

        if not segmento_publico and perfil:
            espec = perfil.get("especializacoes") or []
            if isinstance(espec, list):
                espec_clean = [str(e).strip() for e in espec if str(e).strip()]
            else:
                espec_clean = [str(espec).strip()] if str(espec).strip() else []

            if espec_clean:
                # Ex.: "Barbeiro / Cabelereiro"
                segmento_publico = " / ".join(espec_clean[:2])
            else:
                segmento_publico = perfil.get("segmento")

        if not segmento_publico:
            segmento_publico = base_env["segmentoPublico"]

        # ----- descricaoPublica -----
        descricao_publica = (
            data.get("descricaoPublica")
            or data.get("descricao_publica")
            or data.get("mensagemBoasVindas")
            or data.get("headline")
            or base_env["descricaoPublica"]
        )

        return {
            "nomePublico": nome_publico,
            "segmentoPublico": segmento_publico,
            "descricaoPublica": descricao_publica,
        }

    except Exception:
        logging.exception("conta_status: erro ao ler perfil público para uid=%s", uid)
        return base_env


# ============================================================
# 3) A partir daqui o arquivo segue igual como estava
# ============================================================

def _resolve_uid():
    """
    Resolve o UID do profissional a partir de:
    - querystring ?uid=...
    - g.uid (se já tiver sido setado em algum middleware)
    - Bearer token (get_uid_from_bearer), se disponível
    """
    # 1) uid explícito na query
    uid = request.args.get("uid")
    if uid:
        return uid

    # 2) uid no contexto global
    try:
        if hasattr(g, "uid") and g.uid:
            return g.uid
    except Exception:
        pass

    # 3) Bearer
    if get_uid_from_bearer:
        try:
            uid = get_uid_from_bearer(request)  # type: ignore[arg-type]
            if uid:
                return uid
        except Exception:
            logging.exception("conta_status: falha ao extrair uid do bearer")

    return None


def _snapshot_empresa_from_firestore(uid: str):
    """
    Tenta montar o snapshot da empresa a partir do Firestore.
    Se não conseguir, devolve _snapshot_empresa().
    """
    base_env = _snapshot_empresa()

    if not uid or db is None:
        return base_env

    try:
        # 1) Tentativa principal: profissionais/{uid}/config/empresa
        doc = (
            db.collection("profissionais")
              .document(uid)
              .collection("config")
              .document("empresa")
              .get()
        )
        data = doc.to_dict() if doc.exists else None

        # 2) Fallback: profissionais/{uid}/config/cadastro
        if not data:
            doc2 = (
                db.collection("profissionais")
                  .document(uid)
                  .collection("config")
                  .document("cadastro")
                  .get()
            )
            data = doc2.to_dict() if doc2.exists else None

        # 3) Fallback: profissionais/{uid}
        if not data:
            doc3 = db.collection("profissionais").document(uid).get()
            data = doc3.to_dict() if doc3.exists else None

        if not data:
            return base_env

        # ---- Mapeamento flexível de campos ----
        cnpj = (
            data.get("cnpj")
            or data.get("CNPJ")
            or data.get("cnpjNumero")
            or data.get("cnpj_numero")
            or data.get("cnpjFormatado")
            or base_env["cnpj"]
        )

        razao = (
            data.get("razaoSocial")
            or data.get("razao_social")
            or data.get("razao")
            or data.get("nomeEmpresarial")
            or base_env["razaoSocial"]
        )

        fantasia = (
            data.get("nomeFantasia")
            or data.get("nome_fantasia")
            or data.get("fantasia")
            or base_env["nomeFantasia"]
        )

        # Endereço pode estar aninhado ou flat
        end = data.get("endereco") or {}
        municipio = (
            end.get("municipio")
            or end.get("municipioDescricao")
            or data.get("municipio")
            or data.get("cidade")
            or base_env["endereco"]["municipio"]
        )
        uf = (
            end.get("uf")
            or data.get("uf")
            or data.get("estado")
            or base_env["endereco"]["uf"]
        )

        # ======================================================
        # =============  PATCH DO CNAE (NOVO BLOCO) ============
        # ======================================================

        cnae_codigo = None
        cnae_desc = None

        atividade_principal = (
            data.get("atividade_principal")
            or data.get("atividadePrincipal")
            or data.get("atividade_principal_receita")
        )
        if isinstance(atividade_principal, list) and atividade_principal:
            first = atividade_principal[0] or {}
            cnae_codigo = (
                first.get("code")
                or first.get("codigo")
                or first.get("cod")
            )
            cnae_desc = (
                first.get("text")
                or first.get("descricao")
                or first.get("descricao_cnae")
            )

        # 2) Alternativas flat/aninhadas
        if not cnae_codigo or not cnae_desc:
            cnae = data.get("cnaePrincipal") or data.get("cnae_principal") or {}
            cnae_codigo = (
                cnae.get("codigo")
                or data.get("cnaePrincipalCodigo")
                or data.get("cnae_principal_codigo")
                or data.get("cnae_fiscal")
                or cnae_codigo
            )
            cnae_desc = (
                cnae.get("descricao")
                or data.get("cnaePrincipalDescricao")
                or data.get("cnae_principal_descricao")
                or data.get("cnae_fiscal_descricao")
                or cnae_desc
            )

        # Se não achamos NENHUM CNAE específico nos dados da empresa,
        # é melhor deixar em branco do que usar o SNAP_* "genérico/mentiroso".
        if not cnae_codigo and not cnae_desc:
            cnae_codigo = None
            cnae_desc = None
        else:
            if not cnae_codigo:
                cnae_codigo = base_env["cnaePrincipal"]["codigo"]
            if not cnae_desc:
                cnae_desc = base_env["cnaePrincipal"]["descricao"]

        # ------------------------------------------------------
        # Ajuste coerência:
        # ------------------------------------------------------
        cnpj_base = base_env["cnpj"]
        razao_base = base_env["razaoSocial"]
        fantasia_base = base_env["nomeFantasia"]

        if cnpj and cnpj != cnpj_base:
            if razao == razao_base:
                razao = None
            if fantasia == fantasia_base:
                fantasia = None

        return {
            "cnpj": cnpj,
            "razaoSocial": razao,
            "nomeFantasia": fantasia,
            "endereco": {
                "municipio": municipio,
                "uf": uf,
            },
            "cnaePrincipal": {
                "codigo": cnae_codigo,
                "descricao": cnae_desc,
            },
        }

    except Exception:
        logging.exception("conta_status: erro ao ler empresa do Firestore para uid=%s", uid)
        return base_env


def _vinculo_dict(score: int, limiar: int):
    ok = score >= limiar
    return {
        "stripe_enabled": ok,
        "needs_docs": not ok,
        "pending_review": False,
        "reason": "ok" if ok else "needs_docs",
        "scoreVinculo": score,
        "limiar": limiar,
    }


# -------- endpoints --------
@bp_conta.get("/api/stripe/gate")
def stripe_gate():
    limiar = _env_int("AUTOPASS_LIMIAR", 75)
    score = _env_int("SCORE_VINCULO", 82)
    out = _vinculo_dict(score, limiar)
    resp = make_response(jsonify(out), 200)
    return _no_store(resp)


# ============================================================
# 4) AJUSTE FINAL — HANDLER /api/conta/status
# ============================================================
@bp_conta.get("/api/conta/status")
def conta_status():
    limiar = _env_int("AUTOPASS_LIMIAR", 75)
    score = _env_int("SCORE_VINCULO", 82)

    uid = _resolve_uid()
    if uid:
        empresa = _snapshot_empresa_from_firestore(uid)
        publico = _snapshot_publico_from_firestore(uid)
    else:
        empresa = _snapshot_empresa()
        publico = _snapshot_publico_from_firestore(None)

    vinculo = _vinculo_dict(score, limiar)

    resp = make_response(jsonify({
        "empresa": empresa,
        "publico": publico,
        "vinculo": vinculo
    }), 200)
    return _no_store(resp)

