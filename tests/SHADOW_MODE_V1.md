OBJETIVO

Registrar a validação estrutural do Firestore V2.

VALIDAÇÃO OBRIGATÓRIA

Snapshot deve preservar:

* commercial_runtime
* operational_runtime
* medical_runtime
* behavior_components
* snapshot_priority

Context deve disponibilizar:

* commercial_runtime
* operational_runtime
* medical_runtime
* behavior_components
* snapshot_priority

Segment Profile deve continuar disponível.

Campos legados devem continuar disponíveis.

CRITÉRIO DE APROVAÇÃO

Nenhum campo antigo desaparece.

Nenhum campo V2 desaparece.

Nenhum erro de compilação.

Validador de fixtures executa com sucesso.
