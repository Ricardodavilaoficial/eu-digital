OBJETIVO

Padronizar a criação e manutenção dos testes da Fábrica de Segmentos.

REGRA 1

Todo novo subsegmento aprovado deve possuir:

* JSON Firestore
* Fixture Firestore V2
* Validação da fixture

REGRA 2

Toda alteração em:

* wa_bot.py
* kb_resolver.py
* conversational_front.py

deve executar:

python -m py_compile services\wa_bot.py

python -m py_compile services\kb_resolver.py

python -m py_compile services\conversational_front.py

python tests\validate_firestore_v2_fixtures.py

antes de ser considerada concluída.

REGRA 3

Não testar respostas exatas do GPT.

Testar:

* contratos
* snapshot
* contexto
* regressões estruturais

REGRA 4

Os campos obrigatórios Firestore V2 são:

* commercial_runtime
* operational_runtime
* medical_runtime
* behavior_components
* snapshot_priority

REGRA 5

Nenhum novo subsegmento entra na fábrica sem passar pelas validações acima.
