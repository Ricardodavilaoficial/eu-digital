# RESPONSE MODE MAP

Objetivo:
mapear os usos espalhados de response_mode no conversational_front.py.

Ainda NÃO é documento de refatoração.
É apenas auditoria estrutural.

---

# ZONA CENTRAL (pipeline delimitado)

## 12168+

Pipeline final já delimitado:
- DIRECT
- DISCOVERY
- SCENE
- CLOSING

Responsável por:
- acabamento estrutural
- spoken sync
- discovery identity guard

---

# Usos espalhados a investigar

## DIRECT

- 8792
- 8818
- 9101
- 9559
- 9872
- 10302
- 10416
- 12174

## DISCOVERY

- 1658
- 10527
- 10535
- 12178
- 12200
- 12253

## SCENE

- 1956
- 8893
- 8898
- 8982
- 9041
- 9059
- 9168
- 9709
- 9891
- 10042
- 12192

## CLOSING

- 9529
- 12196

---

# Próximo objetivo

Classificar cada uso como:

- PRE-DECISION
- RUNTIME
- SURFACE SHAPING
- FINAL PIPELINE
- LEGACY
- DUPLICATE