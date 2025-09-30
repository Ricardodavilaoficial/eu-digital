"""
MEI Robô — v1 Schedule Rules (client-editable)
------------------------------------------------
Documento de referência para salvar em:
  profissionais/{uid}/config/schedule_rules

Não é importado pelo código ainda — serve como contrato para UI/motor.
"""

DEFAULT_RULES = {
    "version": 1,
    "timezone": "America/Sao_Paulo",
    "lead_time_hours": 48,     # mínimo de antecedência
    "slot_size_min": 30,       # duração de cada slot
    "working_days": ["MON","TUE","WED","THU","FRI"],
    "working_hours": [
        {"day": "MON", "ranges": [["09:00","12:00"], ["14:00","19:00"]]},
        {"day": "TUE", "ranges": [["09:00","12:00"], ["14:00","19:00"]]},
        {"day": "WED", "ranges": [["09:00","12:00"], ["14:00","19:00"]]},
        {"day": "THU", "ranges": [["09:00","12:00"], ["14:00","19:00"]]},
        {"day": "FRI", "ranges": [["09:00","12:00"], ["14:00","19:00"]]}
    ],
    "blackout_dates": [],      # ["2025-12-24", "2025-12-25"]
    "max_daily_bookings": 12,
    "allow_weekend": False,
    "allow_same_day": False,
    "buffer_min": 10,          # intervalo mínimo entre atendimentos
    "breaks_min": 0            # pausas automáticas (p/ v1.1)
}
