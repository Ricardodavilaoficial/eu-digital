"""
MEI Robô — Domínio de agendamento (V1.0 pré-produção)

Contrato estável:
    propose(
        uid: str,
        service_slug: str | None = None,
        duration_min: int | None = None,
        start_dt: "datetime" | None = None,
        window_days: int = 10,
        max_slots: int = 12,
    ) -> {"slots": list[str], "regra": str}

Regras padrão (podem ser sobrescritas por config Firestore quando houver DB):
  - Sem fins de semana (sábado/domingo)
  - Antecedência mínima de 2 dias a partir de agora
  - Janela de atendimento 09:00–18:00
  - Passo entre slots: 30 minutos
  - Conflitos: evita horários já ocupados com estado "solicitado" ou "confirmado"

Modo offline (quando FIREBASE_PROJECT_ID não está definido):
  - Não acessa Firestore; usa apenas as regras padrão
  - Gera slots sem verificar conflitos (ocupação vazia)
"""

from __future__ import annotations
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta, time, timezone
import logging
import os
import re
import unicodedata

# ================== TZ ==================
SP_TZ = timezone(timedelta(hours=-3))  # America/Sao_Paulo (sem DST)

# ================== Firestore client (tolerante) ==================
_DB = None
_LAST_ERR = None

try:
    from services import db as _db_abs  # type: ignore
    _DB = getattr(_db_abs, "db", None)
except Exception as e_abs:
    _LAST_ERR = f"abs:{e_abs}"
    _db_abs = None  # type: ignore

if _DB is None:
    try:
        from ..services import db as _db_rel  # type: ignore
        _DB = getattr(_db_rel, "db", None)
    except Exception as e_rel:
        _LAST_ERR = (_LAST_ERR or "") + f" | rel:{e_rel}"
        _db_rel = None  # type: ignore


def _db_ready() -> bool:
    """Retorna True somente se houver client e FIREBASE_PROJECT_ID definido."""
    return (_DB is not None) and bool(os.getenv("FIREBASE_PROJECT_ID"))


def _strip_accents_lower(s: str) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower().strip()


def _parse_hhmm(s: str, default: time) -> time:
    try:
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s))
        if not m:
            return default
        hh = max(0, min(23, int(m.group(1))))
        mm = max(0, min(59, int(m.group(2))))
        return time(hour=hh, minute=mm, tzinfo=SP_TZ)
    except Exception:
        return default


def _get_doc_ref(path: str):
    """Não acessa Firestore se _db_ready() for False."""
    if not _db_ready():
        return None
    ref = _DB
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 0:
        return None
    for i, part in enumerate(parts):
        ref = ref.collection(part) if i % 2 == 0 else ref.document(part)
    return ref


def _get_col_ref(path: str):
    """Não acessa Firestore se _db_ready() for False."""
    if not _db_ready():
        return None
    ref = _DB
    parts = [p for p in (path or "").split("/") if p]
    if not parts or len(parts) % 2 != 1:
        return None
    for i, part in enumerate(parts):
        ref = ref.collection(part) if i % 2 == 0 else ref.document(part)
    return ref


def _get_doc(path: str) -> Optional[Dict[str, Any]]:
    ref = _get_doc_ref(path)
    if ref is None:
        return None
    try:
        snap = ref.get()
        return snap.to_dict() if getattr(snap, "exists", False) else None
    except Exception as e:
        logging.info("[scheduling] get doc falhou: %s", e)
        return None


def _list_col(path: str, limit: int = 500) -> List[Dict[str, Any]]:
    col = _get_col_ref(path)
    out: List[Dict[str, Any]] = []
    if col is None:
        return out
    try:
        for d in col.limit(int(limit)).stream():  # type: ignore
            obj = d.to_dict() or {}
            obj["_id"] = d.id
            out.append(obj)
    except Exception as e:
        logging.info("[scheduling] list col falhou: %s", e)
    return out


# ================== Config / Duração ==================
def _load_agenda_config(uid: str) -> Dict[str, Any]:
    """
    Carrega configuração de agenda do profissional.

    Canonical:
      profissionais/{uid}/config/agendamento

    Compat:
      tenta também profissionais/{uid}/configAgendamento (legado).

    Defaults:
      - diasAtendimento: seg–sex
      - atendimentoInicio: 09:00
      - atendimentoFim: 18:00
      - intervaloMin: 30
      - antecedenciaMinDias: 2
    """
    base_cfg: Dict[str, Any] = {}

    if _db_ready():
        # Novo caminho canônico
        cfg_new = _get_doc(f"profissionais/{uid}/config/agendamento") or {}
        # Caminho legado (provavelmente vazio, mas mantemos por segurança)
        cfg_old = _get_doc(f"profissionais/{uid}/configAgendamento") or {}
        base_cfg.update(cfg_new or cfg_old or {})

        # Herda alguns campos do doc principal, se ainda não estiverem na config
        prof = _get_doc(f"profissionais/{uid}") or {}
        for k in ("atendimentoInicio", "atendimentoFim", "intervaloMin"):
            if k not in base_cfg and k in prof:
                base_cfg[k] = prof[k]

    # Defaults seguros
    if "atendimentoInicio" not in base_cfg:
        base_cfg["atendimentoInicio"] = "09:00"
    if "atendimentoFim" not in base_cfg:
        base_cfg["atendimentoFim"] = "18:00"
    if "intervaloMin" not in base_cfg:
        base_cfg["intervaloMin"] = 30

    # Dias de atendimento: 1=Seg, …, 7=Dom
    dias = base_cfg.get("diasAtendimento")
    if not isinstance(dias, (list, tuple)) or not dias:
        base_cfg["diasAtendimento"] = [1, 2, 3, 4, 5]  # seg–sex

    # Antecedência mínima em dias
    lead = base_cfg.get("antecedenciaMinDias")
    try:
        lead_int = int(lead)
    except Exception:
        lead_int = 2
    if lead_int < 0:
        lead_int = 0
    if lead_int > 30:
        lead_int = 30
    base_cfg["antecedenciaMinDias"] = lead_int

    return base_cfg


def _resolve_duration(uid: str, service_slug: Optional[str], default_min: int) -> int:
    if not service_slug or not _db_ready():
        return default_min
    items = _list_col(f"profissionais/{uid}/produtosEServicos", limit=500)
    t = _strip_accents_lower(service_slug)
    best = None
    for it in items:
        slug = (it.get("slug") or "").strip().lower()
        if slug and slug == t:
            best = it
            break
    if not best:
        for it in items:
            name = _strip_accents_lower(it.get("nome") or "")
            if t and t in name:
                best = it
                break
    if best:
        dur = best.get("duracaoMin") or best.get("duracao") or best.get("duracaoPadraoMin")
        try:
            dur_int = int(dur)
            if 5 <= dur_int <= 600:
                return dur_int
        except Exception:
            pass
    return default_min


# ================== Ocupação / Conflitos ==================
def _load_busy(uid: str, start: datetime, end: datetime) -> List[Tuple[datetime, datetime]]:
    """Lê agendamentos ativos para marcar ocupação. Offline: lista vazia."""
    if not _db_ready():
        return []
    busy: List[Tuple[datetime, datetime]] = []
    col = _get_col_ref(f"profissionais/{uid}/agendamentos")
    if col is None:
        return busy
    try:
        docs = col.limit(1000).stream()  # type: ignore
        for d in docs:
            obj = d.to_dict() or {}
            estado = (obj.get("estado") or "").lower()
            if estado not in ("solicitado", "confirmado"):
                continue
            ini_s = obj.get("inicio") or obj.get("dataHora")
            if not ini_s:
                continue
            try:
                ini = datetime.fromisoformat(str(ini_s).replace("Z", "+00:00")).astimezone(SP_TZ)
            except Exception:
                continue
            dur = obj.get("duracaoMin") or 60
            try:
                dur = int(dur)
            except Exception:
                dur = 60
            fim = ini + timedelta(minutes=dur)
            if fim <= start or ini >= end:
                continue
            busy.append((ini, fim))
    except Exception as e:
        logging.info("[scheduling] leitura de agendamentos falhou: %s", e)
    busy.sort(key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = []
    for iv in busy:
        if not merged or iv[0] > merged[-1][1]:
            merged.append(iv)
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], iv[1]))
    return merged


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return not (a_end <= b_start or a_start >= b_end)


# ================== Geração de slots ==================
def _ceil_dt(dt: datetime, minutes: int) -> datetime:
    if minutes <= 1:
        return dt
    discard = (dt.minute % minutes)
    if discard == 0 and dt.second == 0 and dt.microsecond == 0:
        return dt
    delta = minutes - discard
    return (dt.replace(second=0, microsecond=0) + timedelta(minutes=delta))


def _fmt_br(dt: datetime) -> str:
    return dt.strftime("%d/%m %H:%M")


def propose(
    uid: str,
    service_slug: Optional[str] = None,
    duration_min: Optional[int] = None,
    start_dt: Optional[datetime] = None,
    window_days: int = 10,
    max_slots: int = 12,
) -> Dict[str, Any]:
    """
    Gera uma lista de horários disponíveis dentro da janela pedida.

    Retorna:
        {"slots": ["dd/mm %H:%M", ...],
         "regra": "Sem fins de semana; antecedência mínima de 2 dias; janela 09:00–18:00; passo 30 min (America/Sao_Paulo)."}
    """
    MIN_LEAD_DAYS = 2
    DEFAULT_START = time(9, 0, tzinfo=SP_TZ)
    DEFAULT_END = time(18, 0, tzinfo=SP_TZ)
    DEFAULT_STEP = 30
    DEFAULT_DUR = 60

    uid = (uid or os.getenv("UID_DEFAULT") or "").strip()
    if not uid:
        return {
            "slots": [],
            "regra": "Sem fins de semana; antecedência mínima de 2 dias; janela 09:00–18:00; passo 30 min (America/Sao_Paulo).",
        }

    cfg = _load_agenda_config(uid)
    start_time = _parse_hhmm(cfg.get("atendimentoInicio", ""), DEFAULT_START)
    end_time = _parse_hhmm(cfg.get("atendimentoFim", ""), DEFAULT_END)
    try:
        step_min = int(cfg.get("intervaloMin", DEFAULT_STEP))
        if step_min not in (10, 15, 20, 30, 45, 60):
            step_min = DEFAULT_STEP
    except Exception:
        step_min = DEFAULT_STEP

    # Dias em que o profissional atende: 1=Seg … 7=Dom
    dias_cfg = cfg.get("diasAtendimento") or [1, 2, 3, 4, 5]
    allowed_weekdays = set()
    for d in dias_cfg:
        try:
            di = int(d)
            # weekday(): 0=Seg … 6=Dom → mapeamos 1..7 pra 0..6
            w = (di - 1) % 7
            allowed_weekdays.add(w)
        except Exception:
            continue

    if not allowed_weekdays:
        allowed_weekdays = {0, 1, 2, 3, 4}  # fallback seg–sex

    dur = duration_min or _resolve_duration(uid, service_slug, DEFAULT_DUR)
    try:
        dur = int(dur)
        if dur < 10 or dur > 600:
            dur = DEFAULT_DUR
    except Exception:
        dur = DEFAULT_DUR

    now = datetime.now(SP_TZ)
    base = (start_dt.astimezone(SP_TZ) if isinstance(start_dt, datetime) else now)

    lead_days = cfg.get("antecedenciaMinDias", MIN_LEAD_DAYS)
    try:
        lead_days = int(lead_days)
    except Exception:
        lead_days = MIN_LEAD_DAYS
    if lead_days < 0:
        lead_days = 0
    if lead_days > 30:
        lead_days = 30

    earliest = (base + timedelta(days=lead_days)).replace(second=0, microsecond=0)
    day_end = (earliest + timedelta(days=window_days)).replace(second=0, microsecond=0)

    busy = _load_busy(uid, earliest, day_end)  # offline → []

    slots: List[str] = []
    cursor = _ceil_dt(earliest, step_min)

    while cursor.date() <= day_end.date() and len(slots) < max_slots:
        # Pula dias fora dos diasAtendimento configurados
        if cursor.weekday() not in allowed_weekdays:
            # avança até o próximo dia permitido, mantendo horário de abertura
            next_day = cursor
            max_hops = 7
            while next_day.weekday() not in allowed_weekdays and max_hops > 0:
                next_day = (next_day + timedelta(days=1)).replace(
                    hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
                )
                max_hops -= 1
            cursor = next_day
            if cursor.date() > day_end.date():
                break
            continue

        day_open = cursor.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        day_close = cursor.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)

        if cursor < day_open:
            cursor = day_open

        if cursor >= day_close:
            cursor = (cursor + timedelta(days=1)).replace(
                hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
            )
            continue

        slot_start = cursor
        slot_end = slot_start + timedelta(minutes=dur)

        if slot_end > day_close:
            cursor = (cursor + timedelta(days=1)).replace(
                hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0
            )
            continue

        conflict = any(_overlaps(slot_start, slot_end, b_ini, b_fim) for b_ini, b_fim in busy)
        if not conflict:
            slots.append(_fmt_br(slot_start))

        cursor = cursor + timedelta(minutes=step_min)

    regra = (
        f"Sem fins de semana; antecedência mínima de {MIN_LEAD_DAYS} dias; "
        f"janela {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}; "
        f"passo {step_min} min (America/Sao_Paulo)."
    )
    return {"slots": slots, "regra": regra}


# ================== Visão de Agenda p/ Dashboard ==================
def _map_estado_to_status_and_level(estado: str) -> tuple[str, str]:
    """
    Converte o 'estado' interno do agendamento para (status, level)
    que o front da agenda entende.
    """
    e = (estado or "").lower().strip()

    # Ajuste fino aqui conforme seus estados atuais
    if e in ("confirmado", "aprovado"):
        return "ocupado", "ok"
    if e in ("solicitado", "pendente", "aguardando", "em_analise"):
        return "pendente", "warn"
    if e in ("cancelado", "no_show"):
        return "cancelado", "danger"

    # fallback genérico
    return "livre", "info"


def build_agenda_view_dashboard(
    uid: str,
    base_date: Optional[datetime] = None,
    days: int = 9,
) -> Dict[str, Any]:
    """
    Monta a visão da agenda para o dashboard (Cliente Zero).

    - Respeita config do profissional (atendimentoInicio, atendimentoFim, intervaloMin).
    - Usa o mesmo fuso SP_TZ e os mesmos agendamentos já usados pelo domínio.
    - Mantém regra atual de "sem fins de semana" (seg–sex).
    - Formato compatível com a agenda.html:

        {
          "tz": "America/Sao_Paulo",
          "today": "YYYY-MM-DD",
          "hoje":   [ {hhmm, cliente, assunto, dur, status, level}, ... ],
          "amanha": [ ... ],
          "semana": [ ... ]  // D+2 a D+8
        }
    """
    uid = (uid or "").strip()
    if not uid:
        return {"tz": "America/Sao_Paulo", "today": "", "hoje": [], "amanha": [], "semana": []}

    # Limite de segurança
    if days <= 0:
        days = 1
    if days > 31:
        days = 31

    # Config da agenda (horário e intervalo) — mesmo usado em propose()
    cfg = _load_agenda_config(uid)
    DEFAULT_START = time(9, 0, tzinfo=SP_TZ)
    DEFAULT_END = time(18, 0, tzinfo=SP_TZ)
    DEFAULT_STEP = 30

    start_time = _parse_hhmm(cfg.get("atendimentoInicio", ""), DEFAULT_START)
    end_time = _parse_hhmm(cfg.get("atendimentoFim", ""), DEFAULT_END)
    try:
        step_min = int(cfg.get("intervaloMin", DEFAULT_STEP))
        if step_min not in (10, 15, 20, 30, 45, 60):
            step_min = DEFAULT_STEP
    except Exception:
        step_min = DEFAULT_STEP

    # Base "hoje" em SP_TZ
    if base_date is None:
        now = datetime.now(SP_TZ)
        base_date = now.date()
    else:
        base_date = base_date.astimezone(SP_TZ).date() if isinstance(base_date, datetime) else base_date

    dates = [base_date + timedelta(days=i) for i in range(days)]
    today_str = base_date.isoformat()
    end_date = dates[-1]

    # Lê agendamentos reais do período, igual o domínio já faz
    col = _get_col_ref(f"profissionais/{uid}/agendamentos")
    agenda_map: Dict[str, Dict[str, Dict[str, Any]]] = {}

    if col is not None and _db_ready():
        try:
            # Limite de 1000 docs por segurança; se aumentar muito, refinamos depois
            for d in col.limit(1000).stream():  # type: ignore
                obj = d.to_dict() or {}
                estado = obj.get("estado") or obj.get("status") or ""
                ini_s = obj.get("inicio") or obj.get("dataHora")
                if not ini_s:
                    continue
                try:
                    ini = datetime.fromisoformat(str(ini_s).replace("Z", "+00:00")).astimezone(SP_TZ)
                except Exception:
                    continue

                # Fora da janela de interesse → ignora
                if ini.date() < base_date or ini.date() > end_date:
                    continue

                date_str = ini.date().isoformat()
                hhmm = ini.strftime("%H%M")

                if date_str not in agenda_map:
                    agenda_map[date_str] = {}
                # Último write ganha (remarcações recentes sobrescrevem)
                agenda_map[date_str][hhmm] = {
                    "estado": estado,
                    "inicio": ini,
                    "duracaoMin": obj.get("duracaoMin") or obj.get("duracao") or 60,
                    "clienteNome": obj.get("clienteNome") or obj.get("cliente") or "",
                    "assunto": obj.get("assunto") or "",
                }
        except Exception as e:
            logging.info("[scheduling.dashboard] leitura de agendamentos falhou: %s", e)

    hoje_list: List[Dict[str, Any]] = []
    amanha_list: List[Dict[str, Any]] = []
    semana_list: List[Dict[str, Any]] = []

    for idx, dt_obj in enumerate(dates):
        # Mantemos regra "sem fins de semana" como no propose() atual
        if dt_obj.weekday() >= 5:  # 5=sábado, 6=domingo
            continue

        date_str = dt_obj.isoformat()
        day_open = datetime.combine(dt_obj, start_time)
        day_close = datetime.combine(dt_obj, end_time)

        cursor = day_open
        while cursor <= day_close:
            hhmm = cursor.strftime("%H%M")
            ag_obj = (agenda_map.get(date_str) or {}).get(hhmm)

            if ag_obj:
                status, level = _map_estado_to_status_and_level(ag_obj.get("estado"))
                dur = ag_obj.get("duracaoMin") or 60
                try:
                    dur = int(dur)
                except Exception:
                    dur = 60
                cliente = ag_obj.get("clienteNome") or ""
                assunto = ag_obj.get("assunto") or ""
            else:
                status = "livre"
                level = "info"
                dur = step_min
                cliente = ""
                assunto = ""

            item = {
                "date": date_str,  # YYYY-MM-DD (para o front agrupar por dia)
                "hhmm": hhmm,
                "cliente": cliente,
                "assunto": assunto,
                "dur": dur,
                "status": status,
                "level": level,
            }

            if idx == 0:
                hoje_list.append(item)
            elif idx == 1:
                amanha_list.append(item)
            else:
                semana_list.append(item)

            cursor = cursor + timedelta(minutes=step_min)

    return {
        "tz": "America/Sao_Paulo",
        "today": today_str,
        "hoje": hoje_list,
        "amanha": amanha_list,
        "semana": semana_list,
    }


# ---------- CLI rápido para debug local ----------
if __name__ == "__main__":
    uid = os.getenv("UID_DEFAULT", "").strip()
    if not uid:
        print("Defina UID_DEFAULT para testar. Ex.: set UID_DEFAULT=ricardo-prod-uid")
    else:
        out = propose(uid=uid, service_slug=os.getenv("SERVICE_SLUG") or None)
        print(out)




# ===============================
# CRIAÇÃO REAL DE AGENDAMENTO
# ===============================

def create_agendamento(
    uid: str,
    wa_key: str,
    inicio_str: str,
    service_slug: Optional[str] = None,
    duracao_min: int = 60,
) -> bool:
    if not _db_ready():
        return False

    try:
        col = _get_col_ref(f"profissionais/{uid}/agendamentos")
        if col is None:
            return False

        doc = col.document()
        doc.set({
            "clienteWaKey": wa_key,
            "inicio": inicio_str,
            "duracaoMin": duracao_min,
            "estado": "confirmado",
            "origem": "whatsapp",
        })

        # 🔔 Enviar e-mail de confirmação para o profissional
        try:
            from services.email_sender import send_confirmation  # type: ignore
            from services.db import db  # type: ignore

            prof = db.collection("profissionais").document(uid).get()
            prof_data = prof.to_dict() or {}
            to_email = (prof_data.get("email") or "").strip()

            if to_email:
                payload = {
                    "cliente": wa_key,
                    "inicio": inicio_str,
                    "duracao": duracao_min,
                }
                send_confirmation(to_email, payload)
        except Exception as e:
            logging.info("[scheduling] email confirmacao falhou: %s", e)

        return True
    except Exception as e:
        logging.info("[scheduling] create_agendamento falhou: %s", e)
        return False
