# routes/stripe_checkout.py
import os
from flask import Blueprint, jsonify, request
import stripe

# Soft-auth (não exige login; tenta identificar via Authorization: Bearer)
from services.auth import get_verified_uid_from_request

# Firestore wrapper (mesmo usado em routes/cupons.py)
from services.db import db

stripe_checkout_bp = Blueprint("stripe_checkout_bp", __name__)

def _abs_url(path: str) -> str:
    """
    Gera URL absoluta para o Stripe/redirects. Prioriza FRONTEND_BASE.
    Se FRONTEND_BASE não estiver setado, cai para request.host_url.
    """
    base = (os.getenv("FRONTEND_BASE") or request.host_url or "").rstrip("/")
    path = path if path.startswith("/") else "/" + path
    return base + path

def _get_secret_key():
    # simples: usa STRIPE_SECRET_KEY; (futuro: chave live/test por STRIPE_MODE)
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY ausente no ambiente")
    return key

def _has_free_coupon(uid: str) -> bool:
    """
    Retorna True se o profissional já tem licença ativa proveniente de CUPOM "nosso".
    Não revalida cupom aqui (validação/consumo já foi feita na rota /api/cupons/ativar).
    Regras simples e seguras:
      - profissionais/{uid}.licenca.origem == "cupom"
      - (opcional) ignorar se houver flag de cancelamento no futuro
    """
    try:
        if not uid:
            return False
        doc = db.collection("profissionais").document(uid).get()
        if not doc or not doc.exists:
            return False
        data = doc.to_dict() or {}
        lic = (data.get("licenca") or {})
        origem = (lic.get("origem") or "").strip().lower()
        # se no futuro existir flag de revogação/cancelamento, podemos checar aqui:
        cancelada = bool(lic.get("cancelada", False))
        return (origem == "cupom") and (not cancelada)
    except Exception:
        # Em caso de falha de leitura do DB, NÃO libera de graça (fail-safe)
        return False

@stripe_checkout_bp.route("/api/stripe/checkout", methods=["GET"])
def api_stripe_checkout():
    """
    Cria uma sessão de Checkout e devolve { checkoutUrl: "https://checkout.stripe.com/..." }
    Suporta cupom via ?cupom= (PromotionCode da Stripe) para quem NÃO tem nosso cupom aplicado.
    Bypass: se o usuário tiver licença ativa com origem "cupom", pula Stripe e manda direto para /pages/ativar-config.html.
    success_url: /pages/ativar-config.html (Frontend)
    cancel_url:  /pages/ativar-cliente.html (Frontend)
    """
    try:
        # 1) BYPASS: se usuário com cupom NOSSO já aplicado → pular Stripe
        uid = get_verified_uid_from_request()
        if uid and _has_free_coupon(uid):
            # redireciona direto para a tela de boas-vindas/ativação
            return jsonify({
                "checkoutUrl": _abs_url("/pages/ativar-config.html?free=1")
            }), 200

        # 2) Caso contrário, segue o fluxo normal do Stripe
        stripe.api_key = _get_secret_key()

        success_url = _abs_url("/pages/ativar-config.html?session_id={CHECKOUT_SESSION_ID}")
        cancel_url  = _abs_url("/pages/ativar-cliente.html?cancel=1")

        # Produto/Preço (exemplo PAYMENT único; ajuste conforme seu plano)
        line_items = [{
            "price_data": {
                "currency": "brl",
                "unit_amount": 2900,  # R$ 29,00 (centavos)
                "product_data": {
                    "name": "MEI Robô - Assinatura",
                    "description": "Plano inicial (Cliente Zero)",
                },
                # Para assinatura mensal, troque para:
                # "recurring": {"interval": "month"}
            },
            "quantity": 1,
        }]

        # 3) Promotion Code do Stripe via ?cupom= (opcional, só para quem NÃO tem cupom nosso)
        cupom = (request.args.get("cupom") or "").strip()
        discounts = None
        if cupom:
            pc = stripe.PromotionCode.list(code=cupom, limit=1)
            if pc and pc.data:
                discounts = [{"promotion_code": pc.data[0].id}]
            else:
                discounts = None  # deixa campo visível no checkout para digitar manualmente

        params = {
            "mode": "payment",                          # ou "subscription", se aplicável
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "automatic_tax": {"enabled": False},
            "allow_promotion_codes": True if not discounts else False,
        }
        if discounts:
            params["discounts"] = discounts

        session = stripe.checkout.Session.create(**params)
        return jsonify({"checkoutUrl": session.url}), 200

    except Exception as e:
        # Não vazar detalhes sensíveis em produção
        return jsonify({"error": "Não foi possível iniciar a assinatura."}), 500
