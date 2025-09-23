# routes/stripe_checkout.py
import os
from flask import Blueprint, jsonify, request
import stripe

stripe_checkout_bp = Blueprint("stripe_checkout_bp", __name__)

def _abs_url(path: str) -> str:
    """
    Gera URL absoluta para o Stripe. Prioriza FRONTEND_BASE.
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

@stripe_checkout_bp.route("/api/stripe/checkout", methods=["GET"])
def api_stripe_checkout():
    """
    Cria uma sessão de Checkout e devolve { checkoutUrl: "https://checkout.stripe.com/..." }
    Suporta cupom via ?cupom= (usa PromotionCode da Stripe, se existir).
    success_url: /pages/ativar-config.html (Frontend)
    cancel_url:  /pages/ativar-cliente.html (Frontend)
    """
    try:
        stripe.api_key = _get_secret_key()

        # >>>>>> ALTERADO: URLs agora apontam para o FRONTEND usando _abs_url
        success_url = _abs_url("/pages/ativar-config.html?session_id={CHECKOUT_SESSION_ID}")
        cancel_url  = _abs_url("/pages/ativar-cliente.html?cancel=1")

        # Produto/Preço da assinatura/ativação:
        # Opção A (rápida p/ teste): define line_items com price_data inline
        # Trocar moeda/valor conforme seu plano.
        line_items = [{
            "price_data": {
                "currency": "brl",
                "unit_amount": 2900,  # R$ 29,00 (centavos)
                "product_data": {
                    "name": "MEI Robô - Assinatura",
                    "description": "Plano inicial (Cliente Zero)",
                },
                # Para pagamento único, deixe sem 'recurring'.
                # Para assinatura mensal, use: "recurring": {"interval": "month"}
            },
            "quantity": 1,
        }]

        # Cupom (Promotion Code no Stripe)
        cupom = (request.args.get("cupom") or "").strip()
        discounts = None
        if cupom:
            # tenta achar PromotionCode com o código recebido (?cupom=MEIROBO89)
            # OBS: o "code" é o texto que o cliente digita; tem que existir em TEST na Stripe
            pc = stripe.PromotionCode.list(code=cupom, limit=1)
            if pc and pc.data:
                discounts = [{"promotion_code": pc.data[0].id}]
            else:
                # fallback: permite digitar manualmente na tela do checkout
                discounts = None  # e abaixo habilitamos allow_promotion_codes=True

        # Monta a sessão
        params = {
            "mode": "payment",                          # para assinatura mensal usar "subscription"
            "line_items": line_items,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "automatic_tax": {"enabled": False},
            "allow_promotion_codes": True if not discounts else False,  # se não pré-aplicou, deixa o campo visível
        }
        if discounts:
            params["discounts"] = discounts

        session = stripe.checkout.Session.create(**params)
        return jsonify({"checkoutUrl": session.url}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
