Arquitetura de IA do MEI Robô — v1.0

(Documento Canônico — IA + Acervo + wa_bot)

0. Contexto e Princípios

O MEI Robô é 100% dependente de parceiros de tecnologia (OpenAI, Google Cloud, Firebase, Render/Cloud Run).
Nosso foco é eficiência, economia e qualidade para o MEI, sem construir infraestrutura pesada.

Princípios:

IA sempre ativa — nada de automação por palavra-chave.

Tokens = custo → otimizar cada requisição.

Dados 100% isolados por cliente.

Arquitetura plugável de parceiros.

RAG enxuto, pragmático e barato.

1. Pipeline de IA (Visão Geral)

Fluxo de resposta do MEI Robô:

Entrada → cliente envia texto/áudio.

STT (se áudio) → transcrição curta.

NLU (LLM mini) → detecta intent, slots, need_acervo.

Context Router → decide qual domínio acionar.

RAG (se necessário) → busca no acervo.

Domínio → gera rascunho factual (preço, agenda, resposta técnica).

Humanizer → aplica clone digital (SCODE).

Saída → texto ou áudio (TTS ElevenLabs).

Resumo curto → grava contexto leve para próxima interação.

2. Acervo (armazenamento + RAG)
2.1 Estrutura em Firestore

profissionais/{uid}/acervo/{id}:

titulo, tipo, tags[], habilitado, prioridade

tamanhoBytes

fonte ∈ {upload, texto_livre}

storageOriginalPath, storageOriginalUrl

storageConsultaPath, storageConsultaUrl

resumoCurto

ultimaIndexacao

criadoEm, atualizadoEm

Quota:
profissionais/{uid}/acervoMeta/meta → soma de bytes + limite.

2.2 Estrutura em GCS (Bucket)

Original:
profissionais/{uid}/acervo/original/{id}.{ext}

Consulta (.md):
profissionais/{uid}/acervo/consulta/{id}.md

2.3 Limites do Plano Starter

2 GB totais por MEI (Acervo + Contatos + anexos).

Máximo por arquivo configurável (ex. 50 MB).

3. RAG (mini-RAG enxuto)
Filosofia

Nada de banco vetorial gigante.

Embeddings sob demanda.

Filtrar por metadados antes de ranking semântico.

Mandar ao LLM só 1–3 trechos curtos.

Assinatura do domínio
query_acervo_for_uid(uid, pergunta, max_tokens=120)


Saída:

{
  "answer": "...",
  "usedDocs": [...],
  "reason": "ok" | "no_docs" | "no_relevant_docs" | "llm_error"
}

Economia

Embeddings gerados apenas quando necessário.

Contexto limitado.

Modelo mini como padrão.

4. NLU e Persona (Clone Digital)
NLU

Modelo: LLM mini.

Input mínimo:

mensagem

resumo da sessão (curto)

SCODE (persona)

Retorno:

intent, slots

need_acervo

tone_hint

Persona / SCODE

Representa o estilo do MEI:

{
  "nomePublico": "...",
  "registroLinguagem": "informal",
  "gírias": ["mano", "irmão"],
  "assinatura": "— Ed",
  "tom": "calmo e direto"
}


É usado tanto na interpretação quanto na resposta final.

5. Contatos e IA

Contatos armazenam relacionamentos, preferências e consentimento.

Nunca enviamos histórico gigante no prompt.

Apenas um resumo de 1–3 bullets.

6. wa_bot (fachada orquestradora)

services/wa_bot.py:

NÃO contém lógica pesada.

Chamadas para:

nlu/

domain/pricing

domain/scheduling

domain/acervo

services/humanizer

É o maestro, não a orquestra.

7. Economia e robustez
Economia

Contexto mínimo.

Limite de tokens por operação.

Cache para perguntas repetidas.

Embeddings sob demanda.

Robustez

Fallback humano quando IA falha.

Logs sem dados sensíveis.

Respostas resilientes.

8. Segurança e LGPD

Isolamento absoluto por MEI.

Consentimento para voz e comunicação.

Inteligência coletiva futura → só com dados agregados e anônimos.

9. Roadmap IA (pós v1.0)

v1.1 — embeddings sob demanda + ranking semântico.

v1.2 — gerar versões magrinhas + resumos automáticos.

v1.3 — refinamento do Context Router (dados reais).

v1.4 — transparência para o MEI (“Por que respondi isso?”).

10. Resumo final

O MEI Robô usa IA 100% do tempo para entender e responder, sempre com economia extrema de tokens, acervo isolado por MEI, contexto mínimo e persona aplicada para parecer um humano de verdade — tudo sobre uma arquitetura leve, plugável e escalável.