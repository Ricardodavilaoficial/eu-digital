# -*- coding: utf-8 -*-
"""
Middleware: Authority Gate (Fase 1)
- Controla o acesso a rotas "oficiais" quando VERIFICACAO_AUTORIDADE=true.
- Se o usuário estiver guest_unverified, retorna 403 e orientações.
- Em PREVIEW usa cabeçalho X-Debug-User para simular usuários.

Ajustes (2025-10-15):
- ALLOWLIST pública para não exigir Authorization/identidade em:
  • /api/cadastro           (cadastro deve ser público + captcha)
  • /api/cnpj/*             (consultas CNPJ são públicas)
  • /captcha/verify         (validação de captcha)
  • /health                 (sanidade)
- Essa allowlist é aplicada ANTES de verificar padrões restritos, garantindo
  que signup e CNPJ fluam mesmo com o gate ativo.
"""
import os, re
from flask import request, jsonify
from models.user_status import get_user_status, StatusConta

# Caminhos sempre públicos (sem exigir Authorization)
PUBLIC_ALLOWLIST = {
    "/health",
    "/captcha/verify",
    "/api/cadastro",
}

# Prefixos sempre públicos (todas as subrotas liberadas)
PUBLIC_PREFIXES = (
    "/api/cnpj",   # cobre /api/cnpj/availability e /api/cnpj/<cnpj>
,)

def init_authority_gate(app, restricted_patterns=None):
    """
    Registra before_request que aplica o gate apenas quando a flag estiver ativa.
    restricted_patterns: lista de regex (strings) das rotas a proteger.
    Ex.: [r"^/api/cupons/.*", r"^/api/importar-precos$", r"^/admin/.*", r"^/webhook/.*"]
    """
    if restricted_patterns is None:
        restricted_patterns = []

    compiled = [re.compile(p) for p in restricted_patterns]

    def _flag_on() -> bool:
        return os.getenv("VERIFICACAO_AUTORIDADE", "false").lower() == "true"

    def _matches_any(path: str) -> bool:
        return any(rx.search(path) for rx in compiled)

    def _is_public(path: str) -> bool:
        # libera caminhos exatos
        if path in PUBLIC_ALLOWLIST:
            return True
        # libera por prefixo
        for pref in PUBLIC_PREFIXES:
            if path.startswith(pref):
                return True
        return False

    @app.before_request
    def _authority_gate_hook():
        # Gate só atua se a flag estiver ON
        if not _flag_on():
            return  # NO-OP

        path = (request.path or "/").strip()

        # 1) Sempre liberar rotas públicas
        if _is_public(path):
            return  # segue fluxo sem exigir token/identidade

        # 2) Fora do escopo de restrições? Libera.
        if not _matches_any(path):
            return  # fora do escopo

        # 3) A partir daqui, aplica verificação de autoridade/identidade
        #    Identidade (preview): cabeçalho X-Debug-User; em produção, trocar por auth real
        uid = request.headers.get("X-Debug-User", "guest")

        status, exp = get_user_status(uid)

        if status == StatusConta.guest_unverified:
            # bloqueia apenas rotas oficiais configuradas
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
