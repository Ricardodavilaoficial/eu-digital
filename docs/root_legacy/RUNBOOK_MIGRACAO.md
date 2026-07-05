# RUNBOOK — Migração Render ↔ Cloud Run (MEI Robô) — v1.2

## Objetivo
Trocar o backend ativo (Cloud Run ⇄ Render) sem quebrar:
- Webhook YCloud (/integracoes/ycloud/webhook)
- Cloud Tasks (queue ycloud-inbound)
- Worker (/tasks/ycloud-inbound)
- Resposta no WhatsApp (áudio/texto)
- Auditoria no Firestore

---

## Conceito: “Quem está ativo”
O backend ativo é o que recebe:
1) YCloud webhook: POST /integracoes/ycloud/webhook
2) Cloud Tasks dispatch: POST /tasks/ycloud-inbound

---

## Variáveis críticas (devem bater)
### Em qualquer ambiente (Cloud Run ou Render)
- CLOUD_TASKS_SECRET (header: X-MR-Tasks-Secret deve bater)
- BACKEND_BASE / BACKEND_BASE_URL apontando para o backend ATIVO
- GCP_CREDENTIALS_MODE=adc_or_inline (recomendado)
- FIREBASE_SERVICE_ACCOUNT_JSON com private key (necessário p/ Signed URL V4)
- NÃO usar GOOGLE_APPLICATION_CREDENTIALS com JSON inline

---

## Checklist: Render → Cloud Run
1) Deploy Cloud Run (serviço mei-robo-inst2) ok
2) Confirmar POST worker aceita:
   - curl POST /tasks/ycloud-inbound (não pode 405)
3) No painel YCloud, apontar webhook para:
   - https://<cloudrun>/integracoes/ycloud/webhook
4) Enviar áudio no WhatsApp e conferir:
   - logs: enqueued_ok
   - logs: [tasks] start
   - resposta chega no WhatsApp

---

## Checklist: Cloud Run → Render
1) Render com ENVs completos e atualizados
2) Confirmar POST worker aceita no Render:
   - curl POST /tasks/ycloud-inbound (não pode 405)
3) No painel YCloud, apontar webhook para:
   - https://<render>/integracoes/ycloud/webhook
4) Enviar áudio no WhatsApp e conferir:
   - logs Render: enqueued_ok
   - logs Render: [tasks] start
   - resposta chega no WhatsApp

---

## Smoke tests (CMD)
### Worker precisa aceitar POST (não pode 405)
curl -i -X POST "https://<HOST>/tasks/ycloud-inbound" ^
  -H "Content-Type: application/json" ^
  -H "X-MR-Tasks-Secret: <SECRET>" ^
  -d "{\"eventKey\":\"manual_smoke\",\"payload\":{\"msgType\":\"text\",\"wamid\":\"manual_smoke\"}}"

### Logs (Cloud Run)
gcloud run services logs read mei-robo-inst2 ^
  --region southamerica-east1 ^
  --freshness=10m ^
  --limit 4000 ^
| findstr /i /c:"enqueued_ok" /c:"[tasks] start" /c:"outbox_immediate" /c:"sent_ok=True" /c:"deduped"

---

## Padrão de produto (Pacote 2): “Áudio + texto copiável”
- Se lead fechar por áudio (“assinar/procedimento”):
  - 1 áudio ACK curto (MP3) + 1 texto com link copiável
- Anti-duplicidade:
  - dedupe inbound por eventKey
  - semáforo did_send_audio (não reenviar áudio no mesmo worker)
- Auditoria:
  - sentVia=send_audio_ack_then_text
