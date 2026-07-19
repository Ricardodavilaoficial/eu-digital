# MODO OPERANTE CANÔNICO — WORK + CODEX + CMD

O desenvolvimento do MEI Robô será conduzido por três camadas complementares:

## 1. WORK — CONDUÇÃO E GOVERNANÇA

Work é responsável por:

* compreender o problema;
* preservar o contexto amplo;
* realizar análise de risco;
* definir o objetivo e o escopo;
* proteger os pilares canônicos;
* aprovar cada movimento técnico;
* interpretar resultados;
* decidir se o trabalho pode avançar para staging, commit, push ou deploy.

## 2. CODEX — EXECUÇÃO TÉCNICA LOCAL

Codex é responsável por operar diretamente no workspace local autorizado.

Pode, quando a missão permitir:

* inspecionar arquivos e estado Git;
* executar comandos;
* criar scripts temporários controlados;
* executar esses scripts;
* rodar compilação e testes;
* inspecionar diffs;
* remover scripts temporários;
* realizar alterações cirúrgicas;
* atualizar staging seletivamente;
* devolver evidências objetivas da execução.

Codex deve trabalhar somente dentro da pasta autorizada do projeto.

## 3. CMD — PADRÃO OPERACIONAL

Toda execução local deve respeitar:

* Windows CMD puro;
* sem PowerShell;
* sem IDE como requisito operacional;
* nunca usar `git add .`;
* não imprimir secrets, tokens, `.env` ou credenciais;
* apagar scripts temporários após o uso;
* executar `py_compile` antes de rodar scripts novos;
* verificar `git status --short --untracked-files=all` antes e depois;
* usar Git como histórico e mecanismo de rollback;
* realizar um movimento controlado por vez.

## 4. MODO EXECUÇÃO CONTROLADA

Aplicável a tarefas determinísticas, como:

* status Git;
* diffs;
* buscas;
* compilação;
* testes existentes;
* probes já definidos;
* staging seletivo aprovado;
* exportação de patches;
* limpeza de temporários.

Neste modo:

* usar raciocínio suficiente, sem investigação expansiva;
* respeitar escopo fechado;
* não alterar arquitetura;
* não ampliar a missão;
* devolver resultados objetivos e exit codes.

## 5. MODO INVESTIGAÇÃO PROFUNDA

Aplicável a:

* bugs difíceis;
* auditoria end-to-end;
* regressões;
* autoridades paralelas;
* persistência;
* memória;
* áudio;
* fallback;
* telemetria;
* comportamento entre turnos;
* análise arquitetural.

Neste modo:

* iniciar read-only;
* inspecionar amplamente o fluxo relevante;
* não propor patch antes de identificar causa comprovada;
* apontar arquivo, função, trecho e cenário concreto;
* separar bloqueadores de riscos não bloqueadores;
* somente alterar após aprovação explícita.

## 6. PILARES CANÔNICOS

Toda missão deve preservar:

* IA soberana;
* GPT-4o-mini compatível;
* prompts determinísticos e positivistas;
* ausência de palavras-chave rígidas novas;
* ausência de profissões hardcoded;
* ausência de árvores de decisão manuais;
* memória, histórico, thread e persistência;
* ordem livre dos turnos;
* comportamento funcional de texto e áudio;
* entrada em áudio gera saída em áudio, salvo contrato legítimo de `SEND_LINK`;
* nenhuma alteração de prompt sem aprovação explícita;
* análise de risco antes de qualquer patch, commit ou deploy.

## 7. CONTRATO MACRO DE SUCESSO CONVERSACIONAL

Uma correção é considerada bem-sucedida somente quando resolve o cenário-alvo sem degradar outras famílias legítimas de interação.

O MEI Robô deve compreender e atender, em qualquer turno e em inúmeras variações de linguagem:

* saudações e aberturas informais;
* conversa social, humor, comentários cotidianos e pequenas digressões;
* perguntas amplas sobre o produto;
* perguntas pontuais sobre preço, ativação, prazo, funcionamento e processo;
* identificação de nome, profissão, segmento ou contexto do lead;
* perguntas sobre aplicação prática no negócio do lead;
* mensagens que combinam identificação, dúvida e intenção comercial;
* intenção de contratar acompanhada de dúvidas ainda não resolvidas;
* pedidos de suporte ou atendimento humano;
* retomadas de assuntos anteriores;
* correções, mudanças de ideia e inversões na ordem da conversa;
* solicitações legítimas de ação, como contratação, pagamento, ativação ou envio de link;
* entradas em texto e áudio.

Essas famílias podem aparecer:

* isoladamente;
* combinadas na mesma mensagem;
* em qualquer ordem;
* no primeiro ou em turnos posteriores;
* depois de uma digressão;
* retomando assunto já tratado.

A resposta deve:

* acolher o conteúdo real da mensagem;
* responder a pergunta explícita prioritária;
* preservar educação, empatia e naturalidade;
* usar humor ou seriedade conforme o contexto;
* aproveitar memória e histórico já persistidos;
* conduzir progressivamente ao trilho comercial ou operacional adequado;
* realizar ação somente quando houver autoridade legítima para ela;
* evitar repetir perguntas já respondidas;
* evitar abandonar uma dúvida apenas porque nome, segmento ou intenção comercial também foram informados.

Exemplos como “Opa”, “Está chovendo aí?”, “Como funciona?”, “Sou advogado, o que isso faz por mim?”, “Quero assinar, mas ainda tenho uma dúvida” e “Como falo com um humano?” são apenas ilustrações de famílias conversacionais.

Eles nunca devem ser transformados em palavras-chave rígidas, respostas prontas ou árvores manuais.

Antes de aprovar qualquer patch conversacional, avaliar regressão cruzada em pelo menos:

1. saudação ou conversa social;
2. pergunta informativa;
3. identificação de nome ou segmento;
4. mensagem com dois ou mais objetivos;
5. intenção comercial com dúvida pendente;
6. fechamento legítimo;
7. pedido de atendimento humano;
8. continuidade entre turnos;
9. texto;
10. áudio.

O sucesso do cenário corrigido não compensa regressão em outra família.

## 8. BARREIRAS DE SEGURANÇA

Por padrão:

* inspeção não autoriza alteração;
* teste aprovado não autoriza staging;
* staging aprovado não autoriza commit;
* commit aprovado não autoriza push;
* push aprovado não autoriza deploy;
* deploy aprovado não dispensa teste real pós-deploy.

Cada transição exige evidência e autorização próprias.
