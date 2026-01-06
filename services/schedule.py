from datetime import datetime, timedelta
import pytz
from dateutil import parser
from .db import db

WEEKEND = {5, 6}  # 5=Saturday, 6=Sunday
TIPOS_VALIDOS = {"visita", "visitaRecebida", "video", "outro"}

def _parse_dt(dt_iso: str):
    return parser.isoparse(dt_iso).astimezone(pytz.UTC)

def validar_agendamento_v1(uid: str, data: dict):
    # obrigatórios mínimos
    for k in ["clienteId", "servicoId", "dataHora"]:
        if not data.get(k):
            return False, f"Campo obrigatório: {k}", None

    start = _parse_dt(data["dataHora"]).replace(second=0, microsecond=0)
    now = datetime.utcnow().replace(tzinfo=pytz.UTC)

    # +2 dias
    if start < now + timedelta(days=2):
        return False, "+2 dias mínimos para agendar.", None
    # Sem fim de semana
    if start.weekday() in WEEKEND:
        return False, "Sem fins de semana.", None

    dur = int(data.get("duracaoMin", 0)) or 30
    end = start + timedelta(minutes=dur)

    # Conflito simples
    col = db.collection(f"profissionais/{uid}/agendamentos").where("estado", "in", ["solicitado", "confirmado"]).stream()
    for d in col:
        ag = d.to_dict()
        ag_start = _parse_dt(ag["dataHora"])
        ag_end   = ag_start + timedelta(minutes=int(ag.get("duracaoMin",30)))
        if not (end <= ag_start or start >= ag_end):
            return False, "Conflito de horário.", None

    tipo = data.get("tipo","outro")
    if tipo not in TIPOS_VALIDOS:
        tipo = "outro"

    novo = {
        "clienteId": data["clienteId"],
        "servicoId": data["servicoId"],
        "dataHora": start.isoformat(),
        "duracaoMin": dur,
        "estado": "solicitado",
        "origem": data.get("origem", "dashboard"),
        "observacoes": data.get("observacoes"),
        "tipo": tipo,
        "local": data.get("local"),
    }
    return True, "ok", novo

def salvar_agendamento(uid: str, ag: dict):
    ref = db.collection(f"profissionais/{uid}/agendamentos").document()
    ref.set(ag)
    ag["id"] = ref.id
    return ag

def atualizar_estado_agendamento(uid: str, ag_id: str, body: dict):
    acao = body.get("acao")
    ref = db.document(f"profissionais/{uid}/agendamentos/{ag_id}")
    snap = ref.get()
    if not snap.exists:
        raise ValueError("Agendamento não encontrado")
    ag = snap.to_dict()

    if acao == "confirmar":
        ag["estado"] = "confirmado"
    elif acao == "cancelar":
        ag["estado"] = "cancelado"
    elif acao == "reagendar":
        nova = body.get("dataHora")
        if not nova:
            raise ValueError("Data/hora obrigatória para reagendar")
        ag["dataHora"] = nova
        ag["estado"] = "solicitado"
    else:
        raise ValueError("Ação inválida")

    ref.set(ag, merge=True)
    ag["id"] = ag_id
    return ag
# -------------------------------------------------------------------
# Compat shim (legacy): alguns módulos esperam "can_book"
# -------------------------------------------------------------------
def can_book(uid: str, data: dict):
    """
    Compatibilidade com wa_bot_legacy.
    Retorna (ok: bool, reason: str).
    """
    ok, reason, _novo = validar_agendamento_v1(uid, data or {})
    return ok, reason


# -------------------------------------------------------------------
# Compat shim (legacy): save_booking
# -------------------------------------------------------------------
def save_booking(uid: str, data: dict):
    """
    Compatibilidade com wa_bot_legacy.
    Apenas delega para o fluxo existente.
    """
    ok, reason, booking = validar_agendamento_v1(uid, data or {})
    if not ok:
        raise ValueError(reason or "booking_failed")
    return booking

