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


def _get_upgrade_price_id():
    """
    Price ID específico do upgrade Starter+ (10 GB).
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

    except Exception as e:
        # Não vazar detalhes sensíveis em produção
        return jsonify({"error": "Não foi possível iniciar a assinatura."}), 500


# ============================================================
# Upgrade de espaço — Starter+ (10 GB) — pagamento único
# ============================================================

@stripe_checkout_bp.route("/api/upgrade/checkout", methods=["POST"])
@auth_required
def api_upgrade_checkout():
    """
    Cria uma sessão de pagamento única para o upgrade Starter+ (10 GB).
    - Requer usuário logado (auth_required + g.user).
    - Usa STRIPE_STARTER_PLUS_PRICE_ID.
    - Guarda mei_uid e upgrade_type na metadata da Session.
    """
    try:
        # 1) Recupera UID do usuário autenticado
        user = getattr(g, "user", None)
        uid = getattr(user, "uid", None)

        if not uid:
            return jsonify({
                "error": {
                    "code": "not_logged_in",
                    "message": "Você precisa estar logado para fazer o upgrade."
                }
            }), 401

        body = request.get_json(silent=True) or {}
        plan = (body.get("plan") or "").strip()

        if plan != "starter_plus_10gb":
            return jsonify({
                "error": {
                    "code": "invalid_plan",
                    "message": "Plano de upgrade inválido."
                }
            }), 400

        stripe.api_key = _get_secret_key()
        price_id = _get_upgrade_price_id()

        success_url = _abs_url("/pages/acervo.html?upgrade=success")
        cancel_url  = _abs_url("/pages/upgrade.html?upgrade=canceled")

        # Pagamento único do upgrade
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            metadata={
                "mei_uid": uid,
                "upgrade_type": "starter_plus_10gb",
            },
            success_url=success_url,
            cancel_url=cancel_url,
        )

        return jsonify({"checkoutUrl": session.url}), 200

    except RuntimeError as e:
        # Erro de configuração (env faltando)
        return jsonify({
            "error": {
                "code": "config_error",
                "message": "Configuração de pagamento não encontrada. Fale com o suporte."
            }
        }), 500
    except Exception as e:
        # Erro genérico de Stripe ou similar
        current_app = None
        try:
            from flask import current_app as _ca
            current_app = _ca
        except Exception:
            pass
        if current_app:
            current_app.logger.exception("[stripe][upgrade_checkout] erro inesperado")
        return jsonify({
            "error": {
                "code": "stripe_error",
                "message": "Não consegui abrir a tela de pagamento agora. Tente de novo em alguns minutos."
            }
        }), 502
