# -*- coding: utf-8 -*-
"""
Middleware: Authority Gate (Fase 1)
- Controla o acesso a rotas "oficiais" quando VERIFICACAO_AUTORIDADE=true.
- Se o usuário estiver guest_unverified, retorna 403 e orientações.
- Em PREVIEW usa cabeçalho X-Debug-User para simular usuários.
"""
import os, re
from flask import request, jsonify
from models.user_status import get_user_status, StatusConta

def init_authority_gate(app, restricted_patterns=None):
    """
    Registra before_request que aplica o gate apenas quando a flag estiver ativa.
    restricted_patterns: lista de regex (strings) das rotas a proteger.
    Ex.: [r"^/api/cupons/.*", r"^/api/importar-precos$", r"^/admin/.*", r"^/webhook/.*"]
    """
    if restricted_patterns is None:
        restricted_patterns = []

    compiled = [re.compile(p) for p in restricted_patterns]

    def _flag_on():
        return os.getenv("VERIFICACAO_AUTORIDADE", "false").lower() == "true"

    def _matches_any(path: str) -> bool:
        return any(rx.search(path) for rx in compiled)

    @app.before_request
    def _authority_gate_hook():
        if not _flag_on():
            return  # NO-OP

        path = request.path or "/"
        if not _matches_any(path):
            return  # fora do escopo

        # Identidade (preview): cabeçalho X-Debug-User; em produção, trocar por auth real
        uid = request.headers.get("X-Debug-User", "guest")
        status, exp = get_user_status(uid)

        if status == StatusConta.guest_unverified:
            # bloqueia apenas rotas oficiais
            payload = {
                "error": "forbidden_unverified",
                "message": "Sua conta precisa ser verificada para acessar esta ação oficial.",
                "como_verificar": [
                    {"metodo": "declaracao", "exemplo_curl": "POST /verificacao/autoridade {metodo: declaracao, dados: {texto: 'Sou autorizado(a)...'}}"},
                    {"metodo": "upload", "observacao": "não envie 'crachá' na v1; use documentos válidos (pendente de análise)."},
                    {"metodo": "convite", "observacao": "envie um convite para um sócio/representante — aceite entra na v1.1."}
                ],
                "rotas_de_ajuda": ["/conta/status", "/verificacao/autoridade"],
                "flagAtiva": True
            }
            return jsonify(payload), 403

        # verified_basic ou verified_owner passam
        return

    # expõe para debug/leitura externa
    app.extensions = getattr(app, "extensions", {})
    app.extensions["authority_gate_patterns"] = restricted_patterns
