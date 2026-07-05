# MEI Robô — Patch v1 (Signed URL + Opt-in UI-only)
Data: 2025-10-01 14:03:16Z

## Novas rotas (Flask/Render)
### Upload seguro
POST /media/signed-url  (auth obrigatória)
Body JSON:
{
  "contentType": "image/jpeg",
  "filename": "foto.jpg"
}
Resposta:
{
  "ok": true,
  "uploadUrl": "... (PUT)",
  "downloadUrl": "... (GET)",
  "path": "sandbox/<SANDBOX_UID>/<uid>/YYYY/MM/DD/<uuid>.jpg",
  "bucket": "<GCS_BUCKET>",
  "expiresInSeconds": 900
}

Fluxo do cliente:
1) Requisita signed-url (acima)
2) Faz PUT binário para `uploadUrl` com header `Content-Type` igual ao enviado
3) Usa `downloadUrl` para exibir/baixar por até 15 min

### Opt-in (UI-only)
POST /api/contacts/{contact_id}/request-optin
POST /api/contacts/{contact_id}/confirm-optin

## Dependências de ambiente
- GCS_BUCKET
- SANDBOX_UID (ex.: demo_uid)
- FIREBASE_* credenciais (para Firestore) — já usadas no app

## Registro dos blueprints (adicionar em app.py)
No topo (após criar o app):
```
from routes.media import media_bp
from routes.contacts import contacts_bp
app.register_blueprint(media_bp)
app.register_blueprint(contacts_bp)
```
(ou use o helper _register_bp se preferir)
