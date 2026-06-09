DECISÃO ARQUITETURAL V2 — CONSULTÓRIO MÉDICO OTORRINOLARINGOLOGIA

Status:
APROVADO

Objetivo:

Consolidar a arquitetura definitiva para evolução do Firestore V2, preservando compatibilidade com o backend atual e permitindo escalabilidade para futuros subsegmentos.

Decisões aprovadas:

1. Não criar Runtime Package neste momento.

Motivos:

- Acervo já implementa recuperação especializada.
- Acervo já possui indexação.
- Acervo já possui compactação.
- Acervo já possui embeddings.
- Acervo já possui recuperação contextual.

2. Firestore permanece como conhecimento canônico do subsegmento.

Responsabilidades:

- Como pensar.
- Como conduzir.
- Como vender.
- Como operar.
- Quais limites respeitar.

3. Acervo permanece como conhecimento específico do profissional.

Responsabilidades:

- Convênios.
- Procedimentos.
- Protocolos locais.
- Regras internas.
- Documentos.
- Materiais técnicos.

4. Nova estrutura lógica Firestore V2.

commercial_runtime
operational_runtime
medical_runtime
behavior_components
snapshot_priority

5. Compatibilidade obrigatória.

Nenhum campo atual será removido.

A evolução ocorrerá por acréscimo de blocos.

6. Backend.

Ajustes futuros concentrados em:

- services/wa_bot.py
- services/kb_resolver.py
- services/bot_handlers/customer_final.py

7. Objetivo estratégico.

Permitir escalar a fábrica para futuros subsegmentos sem criação de novas coleções ou novas camadas de armazenamento.

Status final:

ARQUITETURA APROVADA PARA IMPLEMENTAÇÃO FUTURA.