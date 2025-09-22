# routes/stripe_webhook.py
# Minimal Stripe webhook route (Flask Blueprint)
# - Accepts POST at /webhooks/stripe
# - Verifies Stripe signature using STRIPE_WEBHOOK_SECRET
# - Logs event type and returns 200 quickly

import os
import json
from flask import Blueprint, request, jsonify, current_app

try:
    import stripe
except ImportError as e:
    # Fallback: give a clear error if stripe isn't installed
    stripe = None

stripe_webhook_bp = Blueprint("stripe_webhook_bp", __name__)

@stripe_webhook_bp.route("/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    # Ensure dependency available
    if stripe is None:
        current_app.logger.error("Stripe library not installed. Please add `stripe` to requirements.")
        return jsonify({"error": "stripe_not_installed"}), 500

    endpoint_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not endpoint_secret:
        current_app.logger.error("Missing STRIPE_WEBHOOK_SECRET environment variable.")
        return jsonify({"error": "missing_webhook_secret"}), 500

    # Stripe requires the *raw* request body for signature verification
    payload = request.get_data(cache=False, as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=endpoint_secret)
    except ValueError as e:
        current_app.logger.warning(f"Stripe webhook: invalid payload: {e}")
        return jsonify({"error": "invalid_payload"}), 400
    except stripe.error.SignatureVerificationError as e:
        current_app.logger.warning(f"Stripe webhook: signature verification failed: {e}")
        return jsonify({"error": "invalid_signature"}), 400
    except Exception as e:
        current_app.logger.exception(f"Stripe webhook: unexpected error: {e}")
        return jsonify({"error": "unexpected_error"}), 500

    # At this point, the signature is valid. Acknowledge fast.
    event_type = event.get("type")
    current_app.logger.info(f"[stripe:webhook] Received event: {event_type}")

    # Optionally branch on key events for quick side-effects
    try:
        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            current_app.logger.info(f"[stripe:webhook] checkout.session.completed id={session.get('id')}")
            # TODO: enqueue job to activate license, persist subscription/customer ids, etc.

        elif event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            sub = event["data"]["object"]
            current_app.logger.info(f"[stripe:webhook] subscription event id={sub.get('id')} status={sub.get('status')}")

        elif event_type in ("invoice.payment_succeeded", "invoice.payment_failed"):
            inv = event["data"]["object"]
            current_app.logger.info(f"[stripe:webhook] invoice event id={inv.get('id')} status={inv.get('status')}")
    except Exception as e:
        # Never fail the webhook because of business logic; just log.
        current_app.logger.exception(f"[stripe:webhook] post-process error (ignored): {e}")

    # Always respond 200 quickly so Stripe considers the delivery successful
    return jsonify({"received": True}), 200
