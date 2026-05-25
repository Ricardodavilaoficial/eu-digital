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

## 2026-05-25 — Validação pós-move _front_fmt_brl_from_cents

Após mover `_front_fmt_brl_from_cents` de `conversational_front.py` para `front_utils.py`, o deploy subiu corretamente e o WhatsApp respondeu.

Validação estrutural:
- Cloud Run cold start OK
- sem ImportError
- sem exception
- sem JSON_FAIL_SAFE
- accepted=True
- source=front_structured_python_assembly
- sent_ok=True
- reply_empty=False

Dívida comportamental observada, não causada pela refatoração:
- resposta de agenda longa/genérica/repetitiva
- kbUsed=false
- kbContractId=""
- kbDocPath=""
- kbMissReason="kb_partial_or_missing"
- chars ~817/818
- fallback global PACK_A_AGENDA
- segunda mensagem repetiu o mesmo padrão porque has_name=True, has_segment=False, has_summary=True

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora

## 2026-05-25 — Validação pós-move limpeza textual para front_assembly

Após mover `_drop_explanatory_opening` e `_drop_abstract_closing` para `front_assembly.py`, o deploy subiu corretamente e o WhatsApp respondeu.

Validação estrutural:
- Cloud Run cold start OK
- imports OK
- sem exception
- sem JSON_FAIL_SAFE
- accepted=True
- reply_empty=False
- sent_ok=True

Dívidas comportamentais observadas, não causadas pela refatoração:
- resposta inicial de agenda ainda longa/genérica com kbUsed=false e fallback global PACK_A_AGENDA
- segunda resposta respondeu o local dos agendamentos de forma curta, mas ainda anexou "Me diga seu segmento." de forma deslocada
- has_name=True, has_segment=False, missing_identity=True, identity_question=True, FREE_MODE_FINAL_GUARD ativo

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora

## 2026-05-25 — Validação pós-move builders de runtime pack para front_kb

Após mover `_compose_pack_runtime_short_reply` e `_compose_pack_runtime_compact_reply` para `front_kb.py`, o deploy subiu corretamente e a nova revisão recebeu 100% do tráfego.

Validação estrutural:
- Cloud Run revision `mei-robo-inst2-00297-xj4` com 100% do tráfego
- cold start OK
- imports OK
- blueprints OK
- sem ImportError
- sem exception
- sem JSON_FAIL_SAFE
- accepted=True
- reply_empty=False
- sent_ok=True

Dívidas comportamentais observadas, não causadas pela refatoração:
- resposta de agenda ainda longa/genérica/repetitiva
- kbUsed=false
- kbContractId=""
- kbDocPath=""
- kbMissReason="kb_partial_or_missing"
- chars ~816/819
- fallback global PACK_A_AGENDA
- mensagem 2 também saiu longa, mas seguindo o mesmo fluxo estrutural pré-existente

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora

## 2026-05-25 — Validação pós-move guards de pedido de identidade para front_guards

Após mover `_reply_mentions_name_request`, `_front_identity_request_is_valid` e `_front_has_identity_request_tail` para `front_guards.py`, o deploy subiu corretamente e o WhatsApp respondeu.

Validação estrutural:
- Cloud Build SUCCESS
- Cloud Run deploy OK
- revisão em produção com 100% do tráfego
- cold start OK
- imports OK
- blueprints OK
- sem ImportError
- sem exception
- sem JSON_FAIL_SAFE
- accepted=True
- reply_empty=False
- sent_ok=True
- source=front_structured_python_assembly

Observação do teste:
- o histórico do lead José não foi apagado antes do teste, então a avaliação comportamental ficou menos limpa
- mesmo assim, a validação estrutural foi suficiente

Dívidas comportamentais observadas, não causadas pela refatoração:
- resposta de agenda continua longa/genérica/repetitiva
- kbUsed=false
- kbContractId=""
- kbDocPath=""
- kbMissReason="kb_partial_or_missing"
- has_name=True
- has_segment=False
- fallback global PACK_A_AGENDA
- chars ~811/812

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora

## 2026-05-25 — Validação pós-move operational seed helpers para front_utils

Após mover `_split_user_operational_clauses` e `_build_user_operational_seed` para `front_utils.py`, o build e o deploy subiram corretamente.

Validação estrutural:
- Cloud Build SUCCESS
- Cloud Run deploy OK
- revisão em produção com 100% do tráfego
- cold start OK
- blueprints OK
- sem ImportError
- sem exception
- sem JSON_FAIL_SAFE
- accepted=True
- reply_empty=False
- sent_ok=True
- source=front_structured_python_assembly

Observação:
- as respostas continuam ruins, longas e repetitivas
- isso não parece causado por esta refatoração
- o padrão observado é o mesmo já conhecido: kbUsed=false, kbContractId="", kbDocPath="", kbMissReason="kb_partial_or_missing", sem segmento consolidado e fallback global PACK_A_AGENDA

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora