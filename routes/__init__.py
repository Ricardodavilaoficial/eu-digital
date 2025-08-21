# routes/__init__.py

def register_blueprints(app):
    """
    Registra todos os blueprints disponíveis.
    Os opcionais têm try/except para não quebrar o deploy se faltarem.
    """

    # Blueprints já existentes no seu projeto
    from .routes import routes
    app.register_blueprint(routes)

    from .teste_eleven_route import teste_eleven_route
    app.register_blueprint(teste_eleven_route)

    from .cupons import cupons_bp
    app.register_blueprint(cupons_bp)

    from .core_api import core_api
    app.register_blueprint(core_api)

    # Novos (desta etapa)
    try:
        from .configuracao import config_bp
        app.register_blueprint(config_bp)
    except Exception as e:
        print(f"[warn] config_bp não registrado: {e}")

    try:
        from .importar_precos import importar_bp
        app.register_blueprint(importar_bp)
    except Exception as e:
        print(f"[warn] importar_bp não registrado: {e}")
