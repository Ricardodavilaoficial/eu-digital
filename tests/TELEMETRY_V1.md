OBJETIVO

Documentar a telemetria do Firestore V2.

EVENTO

KB_V2_SNAPSHOT

FINALIDADE

Confirmar que os blocos V2 sobreviveram à construção do snapshot.

CAMPOS OBSERVADOS

* commercial_runtime
* operational_runtime
* medical_runtime
* behavior_components
* snapshot_priority

UTILIZAÇÃO

Quando houver suspeita de regressão:

1. Verificar KB_V2_SNAPSHOT.
2. Confirmar presença dos blocos.
3. Determinar se a perda ocorreu antes ou depois do snapshot.

OBSERVAÇÃO

A telemetria deve registrar presença dos blocos.

Não registrar conteúdo dos blocos.
