# Dívidas comportamentais congeladas — Conversational Front

## 2026-05-25 — Pós Fase 1A

### Sintoma
Perguntas sobre agendamento continuam gerando resposta longa, repetitiva e genérica.

### Evidências
- kbUsed=false
- kbContractId=""
- kbDocPath=""
- kbRequiredOk=false
- kbMissReason=kb_partial_or_missing
- intent=AGENDA
- chars≈814
- source=front_structured_python_assembly
- accepted=True

### Interpretação
O front está operacionalmente vivo, mas respondendo com fallback genérico de platform_kb/packs, sem contrato segmentado/hidratado.

### Decisão
Não corrigir durante a refatoração estrutural.

### Quando revisar
Após isolamento de:
- front_assembly.py
- front_kb.py
- front_understanding.py

## 2026-05-25 — Pós extração _try_parse_kb_json

### Sintoma
Mensagem 2 respondeu corretamente onde acompanhar agendamentos, mas acrescentou “Me diga seu segmento.” de forma pouco natural.

### Evidências
- has_name=True
- has_segment=False
- missing_identity=True
- identity_question=True
- FREE_MODE_FINAL_GUARD ativo
- reply_len=167
- source=front_ia_soberana
- platform_kb_mode=True

### Interpretação
Não é regressão causada pela extração do parser de KB. É comportamento já existente da política de identidade/segmento quando o lead ainda não tem segmento salvo.

### Decisão
Não corrigir agora durante refatoração estrutural. Revisar quando isolarmos front_understanding/front_identity/front_guards.
