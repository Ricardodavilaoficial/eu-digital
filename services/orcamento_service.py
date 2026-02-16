# services/orcamento_service.py
# Serviço isolado para geração e envio de orçamentos automáticos
# Seguro, idempotente e desacoplado do handler principal.

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from services.db import db  # type: ignore
from services.mailer import send_email  # type: ignore


# ==========================================================
# HELPERS
# ==========================================================

def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _compute_hash(payload: Dict[str, Any]) -> str:
    """
    Gera hash estável do conteúdo relevante do orçamento
    (usado para evitar duplicações na mesma conversa).
    """
    base = (
        str(payload.get("servico") or "")
        + str(payload.get("valor") or "")
        + str(payload.get("observacoes") or "")
        + str(payload.get("email") or "")
        + str(payload.get("validUntil") or "")
    )
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def _get_config(uid: str) -> Dict[str, Any]:
    """
    Busca config do timbrado do profissional.
    """
    doc = db.collection("profissionais").document(uid) \
        .collection("config").document("orcamentos").get()

    return doc.to_dict() or {}


def _get_next_numero(uid: str) -> str:
    """
    Gera número sequencial simples (pode evoluir depois).
    """
    col = db.collection("profissionais").document(uid).collection("orcamentos")
    count = col.stream()
    total = sum(1 for _ in count) + 1
    return f"ORC-{datetime.utcnow().year}-{str(total).zfill(5)}"


def _find_last_by_conversation(uid: str, wa_key: str) -> Optional[Dict[str, Any]]:
    """
    Busca o orçamento mais recente desta conversa (conversationKey = wa_key).
    Safe-by-default: retorna None se falhar.
    """
    try:
        q = (
            db.collection("profissionais").document(uid)
            .collection("orcamentos")
            .where("conversationKey", "==", wa_key)
            .order_by("createdAt", direction="DESCENDING")
            .limit(1)
        )
        docs = list(q.stream())
        if not docs:
            return None
        d = docs[0]
        data = d.to_dict() or {}
        data["id"] = d.id
        return data
    except Exception:
        return None



# ==========================================================
# CORE
# ==========================================================

def create_orcamento(
    *,
    uid: str,
    wa_key: str,
    cliente_nome: str,
    cliente_email: str,
    servico: str,
    valor: float,
    observacoes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cria orçamento e salva no Firestore.
    Não envia ainda.
    """

    config = _get_config(uid)
    validade_dias = int(config.get("validadeDias") or 7)

    valid_until = (datetime.utcnow() + timedelta(days=validade_dias)).date().isoformat()

    payload_hash = _compute_hash({
        "servico": servico,
        "valor": valor,
        "observacoes": observacoes,
        "email": cliente_email,
        "validUntil": valid_until,
    })

    # ------------------------------
    # IDEMPOTÊNCIA POR CONVERSA:
    # Se o último orçamento desta conversa tem o mesmo hash, reusa.
    # ------------------------------
    if wa_key:
        last = _find_last_by_conversation(uid, wa_key)
        if isinstance(last, dict):
            last_hash = str(last.get("hashConteudo") or "").strip()
            if last_hash and last_hash == payload_hash:
                # Reusa o mesmo orçamento (não cria outro número/documento)
                return last

    numero = _get_next_numero(uid)

    doc_ref = db.collection("profissionais") \
        .document(uid) \
        .collection("orcamentos") \
        .document()

    data = {
        "numero": numero,
        "origem": "bot",
        "createdAt": _now_iso(),
        "cliente": {
            "nome": cliente_nome,
            "email": cliente_email,
        },
        "servico": servico,
        "valor": valor,
        "observacoes": observacoes,
        "moeda": "BRL",
        "validUntil": valid_until,
        "hashConteudo": payload_hash,
        "conversationKey": wa_key,
        "status": "criado",
    }

    doc_ref.set(data)

    data["id"] = doc_ref.id
    return data


# ==========================================================
# HTML RENDER
# ==========================================================

def render_orcamento_html(uid: str, orc: Dict[str, Any]) -> str:
    """
    Gera HTML do orçamento baseado na config do profissional.
    """

    config = _get_config(uid)

    cor = config.get("corPrincipal") or "#23d366"
    logo = config.get("logoUrl") or ""
    assinatura = config.get("assinaturaUrl") or ""
    carimbo = config.get("carimboUrl") or ""
    nome_empresa = config.get("nomeEmpresa") or "Empresa"
    documento = config.get("documento") or ""
    condicoes = config.get("condicoesPagamento") or ""

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;border:1px solid #eee;padding:24px;border-radius:12px">
      <div style="text-align:center">
        {f'<img src="{logo}" style="max-height:60px;margin-bottom:10px"/>' if logo else ""}
        <h2 style="color:{cor};margin:4px 0">{nome_empresa}</h2>
        <div style="font-size:13px;color:#666">{documento}</div>
      </div>

      <hr style="margin:20px 0"/>

      <h3 style="color:{cor}">Orçamento Nº {orc.get("numero")}</h3>
      <p><strong>Data:</strong> {datetime.utcnow().date().isoformat()}</p>
      <p><strong>Validade:</strong> {orc.get("validUntil")}</p>

      <p><strong>Cliente:</strong> {orc["cliente"]["nome"]}</p>

      <hr/>

      <p><strong>Serviço:</strong> {orc.get("servico")}</p>
      <p><strong>Valor:</strong> R$ {orc.get("valor"):.2f}</p>
      {f'<p><strong>Observações:</strong> {orc.get("observacoes")}</p>' if orc.get("observacoes") else ""}

      <hr/>

      {f'<p><strong>Condições:</strong> {condicoes}</p>' if condicoes else ""}

      <div style="margin-top:30px;text-align:right">
        {f'<img src="{assinatura}" style="max-height:60px;display:block;margin-left:auto"/>' if assinatura else ""}
        {f'<img src="{carimbo}" style="max-height:60px;display:block;margin-left:auto;margin-top:8px"/>' if carimbo else ""}
      </div>
    </div>
    """


# ==========================================================
# ENVIO
# ==========================================================

def send_orcamento_email(
    *,
    uid: str,
    orcamento: Dict[str, Any],
) -> bool:
    """
    Envia orçamento por e-mail e atualiza status.
    """

    html = render_orcamento_html(uid, orcamento)

    subject = f"Orçamento {orcamento.get('numero')}"

    send_email(
        to=orcamento["cliente"]["email"],
        subject=subject,
        html=html,
        text=f"Orçamento {orcamento.get('numero')} - Valor R$ {orcamento.get('valor'):.2f}",
    )

    # Atualiza status
    db.collection("profissionais") \
        .document(uid) \
        .collection("orcamentos") \
        .document(orcamento["id"]) \
        .update({
            "status": "enviado",
            "sentAt": _now_iso(),
            "sentVia": "email",
            "sentTo": orcamento["cliente"]["email"],
        })

    return True
