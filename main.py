# main.py — shim/ponte para usar o app do app.py em produção (Render)
# Mantém o entrypoint esperado (gunicorn main:app), mas reutiliza o app completo
# definido em app.py (webhook, /health, /api/send-text, estáticos, blueprints, etc.)

from app import app  # importa o Flask app já configurado no app.py

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
