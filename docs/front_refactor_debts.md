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

## 2026-05-25 — Validação pós-move `_platform_apply_slots` para `front_kb.py`

Após mover `_platform_apply_slots` de `conversational_front.py` para `front_kb.py`, o build, deploy e teste real no WhatsApp foram concluídos.

Validação estrutural:
- Cloud Build SUCCESS
- Cloud Run deploy OK
- revisão em produção com 100% do tráfego
- cold start OK
- blueprints OK
- sem ImportError
- sem exception
- sem JSON_FAIL_SAFE
- reply_empty=False
- sent_ok=True
- WhatsApp entregou

Sinais positivos:
- `kbUsed=true`
- `kbContractId="clínico geral"`
- `kbDocPath="clínico geral"`
- `segment`, `segment_hint` e `leadSegmentRaw` foram salvos na memória do lead

Dívidas comportamentais observadas, não causadas por esta refatoração:
- intent caiu como `OTHER`
- `accepted=False`
- `hydrated_from_docs=False`
- faltou `example_or_scene`
- resposta curta demais e focada em pedir nome
- duplicação: “Poderia me informar seu nome...” + “Me diga seu nome.”

Decisão:
- não fazer rollback
- não corrigir comportamento nesta fase
- seguir refatoração conservadora

# Pendências comportamentais detectadas durante a refatoração segura

Data: 2026-05-26

## Contexto

Durante a mini auditoria pós-deploy da refatoração estrutural do conversational_front.py, o sistema respondeu no WhatsApp sem quebrar operacionalmente, mas revelou bugs comportamentais já compatíveis com dívidas antigas do front.

Esses pontos NÃO devem ser corrigidos agora, para não interromper a fase de refatoração segura.

## Bugs anotados para correção futura

### 1. PACK_A_AGENDA tutorializando respostas

Quando não há doc real hidratado (`hydrated_from_docs=False`) e o sistema usa `global_pack_fallback=True`, o fallback de agenda ainda produz resposta longa e tutorializada.

Sintomas:
- resposta explica o fluxo inteiro de agendamento;
- pergunta direta vira explicação ampla;
- microcena aparece mesmo sem doc segmentado real.

### 2. Duplicação de material operacional

Em alguns casos, o mesmo conteúdo aparece repetido porque `runtime_short_reply`, `direct_scene`, `operational_reference` e `pack_micro_scene` carregam variações do mesmo PACK_A_AGENDA.

Sintoma:
- resposta repete a mesma ideia duas vezes;
- texto fica longo e redundante.

### 3. JSON_FAIL_SAFE gerando fallback ruim

Quando o modelo falha ao devolver JSON válido, o fluxo cai em `front_free_mode_fallback`.

Sintomas:
- `JSON_FAIL_SAFE`;
- resposta curta demais;
- baixa densidade operacional;
- saída como: `Ho. Me diga seu nome.`

### 4. Saída inválida: "Ho. Me diga seu nome."

Foi detectada uma resposta final com cumprimento deformado:
`Ho. Me diga seu nome.`

Provável origem:
- fallback textual pós-JSON_FAIL_SAFE;
- limpeza/finalização de superfície recebendo texto já ruim;
- não parece causado diretamente pela refatoração atual.

## Decisão

Não corrigir estes bugs agora.

Continuar a refatoração estrutural segura primeiro, para depois corrigir esses pontos com menor risco de regressão.

# Dívida técnica — front_surface.py

`services/front_surface.py` foi criado na FIRST SAFE EXTRACTION WAVE.

Estado atual:
- módulo pequeno;
- boundary limpo;
- helpers puros;
- compile limpo.

Dívida conhecida:
- ainda importa `_normalize_response_mode` de `services.conversational_front`.

Decisão:
- aceitável temporariamente;
- não corrigir agora;
- futura auditoria deve decidir se `_normalize_response_mode` vai para `front_utils.py`, `front_surface.py` ou módulo próprio de response mode.

# STOP REFACTORING POINT

Após a extração de `_sync_spoken_after_technical_rescue(...)` para `services/front_surface.py`, a refatoração estrutural deve pausar.

Motivo:
- próximas funções candidatas começam a encostar em KB/SLA, recovery, governance ou runtime;
- o núcleo restante do `conversational_front.py` já representa majoritariamente RUNTIME SOVEREIGN CORE;
- a prioridade agora passa a ser correção de bugs com boundaries preservados.

Função avaliada e NÃO movida:
- `_sanitize_unverified_time_claims(...)`

Motivo:
- depende de `_kb_get_process_sla_text(...)`;
- lê `kb_snapshot_raw`;
- pertence a sanitize híbrido com KB/SLA.

## 2026-05-27 — Correção estrutural: separação entre identidade humana e contexto de segmento

Commit aplicado:
- 424a692

Contexto:
Durante auditoria do FREE_MODE_FINAL_GUARD, foi identificado que o pipeline de continuidade tratava ausência de segmento como ausência de identidade humana.

Trecho anterior:

```python
_missing_identity = bool(
    not bool(_continuity_has_identity)
    or not bool(_continuity_has_segment)
)



