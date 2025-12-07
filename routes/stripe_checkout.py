# routes/stripe_checkout.py
import os
from flask import Blueprint, jsonify, request, g
import stripe

# Auth forte: exige login e popula g.user (uid, email, etc.)
from services.auth import auth_required

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

def _get_price_id():
    price = os.getenv("STRIPE_PRICE_ID")
    if not price:
        raise RuntimeError("STRIPE_PRICE_ID ausente no ambiente")
    return price

def _get_starter_plus_price_id():
    """
    Price ID específico do plano Starter+ (10 GB).
    Deve estar em STRIPE_STARTER_PLUS_PRICE_ID.
    """
    price = os.getenv("STRIPE_STARTER_PLUS_PRICE_ID")
    if not price:
        raise RuntimeError("STRIPE_STARTER_PLUS_PRICE_ID ausente no ambiente")
    return price

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
@auth_required
def api_stripe_checkout():
    """
    Cria uma sessão de Checkout e devolve { checkoutUrl: "https://checkout.stripe.com/..." }
    Suporta cupom via ?cupom= (PromotionCode da Stripe) para quem NÃO tem nosso cupom aplicado.
    Bypass: se o usuário tiver licença ativa com origem "cupom", pula Stripe e manda direto para /pages/ativar-config.html.
    success_url: /pages/ativar-config.html (Frontend)
    cancel_url:  /pages/ativar-cliente.html (Frontend)
    """
    try:
        # 1) Recupera UID do usuário autenticado
        user = getattr(g, "user", None)
        uid = getattr(user, "uid", None)

        if not uid:
            # em teoria o auth_required já barrou antes, mas deixamos fail-safe
            return jsonify({"error": "Não autenticado"}), 401

        # 2) BYPASS: se usuário com cupom NOSSO já aplicado → pular Stripe
        if _has_free_coupon(uid):
            # redireciona direto para a tela de boas-vindas/ativação
            return jsonify({
                "checkoutUrl": _abs_url("/pages/ativar-config.html?free=1")
            }), 200

        # 3) Caso contrário, segue o fluxo normal do Stripe
        stripe.api_key = _get_secret_key()
        price_id = _get_price_id()

        success_url = _abs_url("/pages/ativar-config.html?session_id={CHECKOUT_SESSION_ID}")
        cancel_url  = _abs_url("/pages/ativar-cliente.html?cancel=1")

        line_items = [{
            "price": price_id,
            "quantity": 1,
        }]

        # Promotion Code do Stripe via ?cupom= (opcional, só para quem NÃO tem cupom nosso)
        cupom = (request.args.get("cupom") or "").strip()
        discounts = None
        if cupom:
            pc = stripe.PromotionCode.list(code=cupom, limit=1)
            if pc and pc.data:
                discounts = [{"promotion_code": pc.data[0].id}]
            else:
                discounts = None  # deixa campo visível no checkout para digitar manualmente

        params = {
            "mode": "subscription",
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

    except Exception:
        # Não vazar detalhes sensíveis em produção
        return jsonify({"error": "Não foi possível iniciar a assinatura."}), 500

# ============================================================
# Novo endpoint: /api/upgrade/checkout  (Starter+ 10 GB)
# ============================================================
@stripe_checkout_bp.route("/api/upgrade/checkout", methods=["POST"])
@auth_required
def api_upgrade_checkout():
    """
    Cria uma sessão de Checkout para o upgrade de espaço (Starter+ 10 GB).
    - Requer usuário logado (auth_required).
    - Usa STRIPE_STARTER_PLUS_PRICE_ID (pagamento único).
    - Envia metadata (upgrade, uid) para o webhook aplicar no Firestore.
    """
    try:
        user = getattr(g, "user", None)
        uid = getattr(user, "uid", None)

        if not uid:
            return jsonify({"error": "Não autenticado"}), 401

        # Lê corpo opcional (plan) só para sanity, mas não depende dele
        body = request.get_json(silent=True) or {}
        plan = (body.get("plan") or "").strip().lower()
        if plan and plan not in ("starter_plus_10gb", "starter+10gb", "starter_plus"):
            # Não bloqueia forte, só loga via retorno
            # (se quiser, podemos relaxar isso e ignorar completamente o plan)
            pass

        stripe.api_key = _get_secret_key()
        price_id = _get_starter_plus_price_id()

        success_url = _abs_url("/pages/acervo.html?upgrade=starter_plus_10gb")
        cancel_url  = _abs_url("/pages/upgrade.html?cancel=1")

        params = {
            # Plano Starter+ também é recorrente (mensal),
            # então usamos Checkout em modo "subscription".
            "mode": "subscription",
            "line_items": [{
                "price": price_id,
                "quantity": 1,
            }],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "automatic_tax": {"enabled": False},
            "metadata": {
                "upgrade": "starter_plus_10gb",
                "uid": uid,
            },
            "client_reference_id": uid,
        }

        session = stripe.checkout.Session.create(**params)
        return jsonify({"checkoutUrl": session.url}), 200

    except Exception:
        return jsonify({"error": "Não foi possível iniciar o upgrade agora. Tente de novo em alguns minutos."}), 500
