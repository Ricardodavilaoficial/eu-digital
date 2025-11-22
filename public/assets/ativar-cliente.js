 <script>
  (function(){
    const API_BASE = "https://mei-robo-prod.onrender.com";
    const API = {
      gate1:   API_BASE + "/api/stripe/gate",
      gate2:   API_BASE + "/api/conta/status",
      checkout:API_BASE + "/api/stripe/checkout",
      cupomValidar: API_BASE + "/api/cupons/validar-publico",
      cupomAtivar:  API_BASE + "/api/cupons/ativar"
    };

    // MOCK DE PREVIEW: ?mock=ready | blocked | unauth | error
    const __qs = new URLSearchParams(location.search);
    const __mock = (__qs.get('mock')||'').toLowerCase();

    const $intro = document.getElementById('intro');
    const $status = document.getElementById('status');
    const $content = document.getElementById('content');
    const $actions = document.getElementById('actions');
    const $btnCheckout = document.getElementById('btnCheckout');
    const $btnDocs = document.getElementById('btnDocs');

    // Cupom UI
    const $couponBox = document.getElementById('couponBox');
    const $codigo = document.getElementById('codigo');
    const $btnValidar = document.getElementById('btnValidar');
    const $btnAplicar = document.getElementById('btnAplicar');
    const $couponMsg = document.getElementById('couponMsg');

    // Estado de cupom
    const cupomState = { valid:false, aplicado:false, codigo:null };

    function pill(text, cls){ $status.textContent = text; $status.className = 'badge ' + (cls || 'muted'); }
    function html(parts){ return parts.filter(Boolean).join(''); }
    function msg(info, type){ $couponMsg.textContent = info; $couponMsg.className = 'hint ' + (type||''); }

    // --- helpers cupom (mesmos do admin, simplificados) ---
    function normalizeCode(v){ return String(v || '').trim().toUpperCase().replace(/[^A-Z0-9-]/g,''); }
    function savePendingCupom(codigo){
      try{ localStorage.setItem('cupomPendente', JSON.stringify({ codigo, ts: Date.now(), ttl: 3600_000 })); }catch{}
    }
    function readPendingCupom(){
      try{
        const raw = localStorage.getItem('cupomPendente'); if(!raw) return null;
        const o = JSON.parse(raw); if(!o || !o.codigo) return null;
        if ((Date.now() - (o.ts||0)) > (o.ttl||0)) { localStorage.removeItem('cupomPendente'); return null; }
        return o.codigo;
      }catch{ return null; }
    }
    function clearPendingCupom(){ try{ localStorage.removeItem('cupomPendente'); }catch{} }

    async function fetchJSON(url, opts){
      const r = await fetch(url, Object.assign({ credentials:'include' }, opts||{}));
      const ct = r.headers.get('content-type') || '';
      const body = ct.includes('application/json') ? await r.json() : await r.text();
      return { ok: r.ok, status: r.status, body };
    }

    function asGate(obj){
      if (!obj || typeof obj !== 'object') return null;
      const stripe_enabled = !!(obj.stripe_enabled ?? obj.stripeEnabled ?? obj.enabled ?? obj.allow ?? obj.gate_ok ?? obj.ok);
      const reason = obj.reason || obj.state || '';
      const needs_docs = !!(obj.needs_docs ?? obj.needsDocs ?? obj.docs ?? obj.need_docs);
      return {
        stripe_enabled,
        reason,
        needs_docs,
        pending_review: !!(obj.pending_review ?? obj.pendingReview),
        scoreVinculo: (typeof obj.scoreVinculo === 'number' ? obj.scoreVinculo : null)
      };
    }

    function renderUnauth(){
      pill('entre para continuar', 'warn');
      $intro.textContent = 'Entre na sua conta para concluir a assinatura.';
      $content.innerHTML = '<p class="muted">Você precisa entrar na sua conta para concluir a assinatura.</p><p><a class="btn-secondary" href="/pages/login.html">Entrar</a></p>';
      // Harden: garante não clicável
      $btnDocs.hidden = true;
      $btnDocs.removeAttribute('href');
      $btnDocs.setAttribute('aria-hidden','true');
      $btnDocs.style.pointerEvents = 'none';
      $actions.hidden = true;
      $couponBox.hidden = true;
    }

    function renderBlocked(o){
      const needs = !!o.needs_docs;
      const pending = !!o.pending_review;
      pill('vínculo pendente', 'warn');
      // Copy ajustada para o estado real
      if (needs) {
        $intro.textContent = 'Precisamos confirmar seu vínculo com a empresa. Envie os documentos para liberar a assinatura.';
      } else if (pending) {
        $intro.textContent = 'Estamos revisando seus documentos. Normalmente finalizamos em poucas horas úteis.';
      } else {
        $intro.textContent = 'Seu vínculo ainda não está liberado para assinatura.';
      }
      $content.innerHTML = html([
        '<p><strong>Precisamos confirmar seu vínculo com a empresa.</strong></p>',
        needs ? '<p class="muted">Envie os documentos solicitados para liberar sua assinatura.</p>' : '',
        pending ? '<p class="muted">Estamos revisando seus documentos. Normalmente leva poucas horas úteis.</p>' : ''
      ]);

      // Harden: só habilita Docs quando realmente precisa
      if (needs) {
        $btnDocs.hidden = false;
        $btnDocs.href = "/pages/vinculo.html";
        $btnDocs.removeAttribute('aria-hidden');
        $btnDocs.style.pointerEvents = '';
      } else {
        $btnDocs.hidden = true;
        $btnDocs.removeAttribute('href');
        $btnDocs.setAttribute('aria-hidden','true');
        $btnDocs.style.pointerEvents = 'none';
      }

      $actions.hidden = false;
      $btnCheckout.disabled = true;
      $btnCheckout.title = "Assinatura liberada após a confirmação do vínculo.";
      $couponBox.hidden = true; // cupom só com gate liberado
    }

    function renderReady(){
      pill('tudo certo ✔', 'ok');
      // Copy afirmativa no mesmo bloco (sem redundância)
      $intro.textContent = 'Conferimos o seu vínculo com a empresa. Está tudo certo — você já pode concluir sua assinatura com segurança.';
      $content.innerHTML = '<p><strong>Seu vínculo está confirmado.</strong> Você pode seguir para a etapa de assinatura com segurança.</p>';
      $actions.hidden = false;
      $btnCheckout.disabled = false;
      $btnCheckout.title = "";

      // Harden: torna Docs realmente inativo
      $btnDocs.hidden = true;
      $btnDocs.removeAttribute('href');
      $btnDocs.setAttribute('aria-hidden','true');
      $btnDocs.style.pointerEvents = 'none';

      // mostra UI de cupom quando liberado
      $couponBox.hidden = false;

      // Preenche com um cupom pendente se existir
      const pend = readPendingCupom();
      if (pend && !$codigo.value) { $codigo.value = pend; msg('Cupom pendente detectado. Clique em Validar.', ''); }
    }

    function renderError(){
      pill('não foi possível verificar agora', 'err');
      $intro.textContent = 'Não foi possível verificar agora. Tente novamente em instantes. Se persistir, fale com o suporte.';
      $content.innerHTML = '<p class="muted">Tente novamente em alguns instantes. Se persistir, fale com o suporte.</p>';
      // Harden: desabilita Docs em erro
      $btnDocs.hidden = true;
      $btnDocs.removeAttribute('href');
      $btnDocs.setAttribute('aria-hidden','true');
      $btnDocs.style.pointerEvents = 'none';
      $actions.hidden = true;
      $couponBox.hidden = true;
    }

    // --- MOCK SWITCH ---
    function __applyMock(){
      if (!__mock) return false;
      if (__mock === 'ready')   { renderReady();   return true; }
      if (__mock === 'blocked') { renderBlocked({ needs_docs:true, pending_review:false }); return true; }
      if (__mock === 'unauth')  { renderUnauth();  return true; }
      if (__mock === 'error')   { renderError();   return true; }
      return false;
    }

    async function load(){
      try{
        // se mock ativo, não chama backend
        if (__applyMock()) return;

        pill('verificando…', 'muted');
        // tenta gate1 e depois gate2
        let g = null;
        const r1 = await fetchJSON(API.gate1).catch(()=>null);
        if (r1 && r1.ok && r1.body) g = asGate(r1.body);
        if (!g) {
          const r2 = await fetchJSON(API.gate2).catch(()=>null);
          if (r2 && r2.ok && r2.body) g = asGate(r2.body);
          if (!g && ((r1 && r1.status===401) || (r2 && r2.status===401))) { renderUnauth(); return; }
        }
        if (!g) { renderError(); return; }

        if (g.stripe_enabled) renderReady();
        else renderBlocked(g);
      } catch(e){
        console.error(e);
        renderError();
      }
    }

    // --- Cupom: validar/aplicar ---
    async function validarCupom(){
      const codigo = normalizeCode($codigo.value);
      if (!codigo) { msg('Digite um código de cupom.', ''); $codigo.focus(); return; }
      msg('Validando…', '');
      $btnValidar.disabled = true; $btnAplicar.disabled = true;
      try{
        const r = await fetchJSON(API.cupomValidar, {
          method:'POST',
          headers:{ 'Content-Type': 'application/json' },
          body: JSON.stringify({ codigo, code: codigo }) // aceita ambas chaves
        });
        const b = r.body || {};
        if (r.ok && (b.ok || b.valido || b.disponivel || b.valid)) {
          cupomState.valid = true; cupomState.codigo = codigo;
          msg('Cupom válido! Clique em Aplicar para vincular à sua conta.', 'msg-ok');
          $btnAplicar.disabled = false;
          savePendingCupom(codigo);
        } else {
          cupomState.valid = false; cupomState.codigo = null;
          msg('Cupom inválido ou indisponível.', 'msg-err');
          $btnAplicar.disabled = true;
          clearPendingCupom();
        }
      } catch(e){
        msg('Falha ao validar agora. Tente novamente.', 'msg-err');
      } finally {
        $btnValidar.disabled = false;
      }
    }

    async function aplicarCupom(){
      const codigo = normalizeCode($codigo.value);
      if (!cupomState.valid || !codigo) { msg('Valide o cupom antes de aplicar.', ''); return; }
      msg('Aplicando…', '');
      $btnAplicar.disabled = true;
      try{
        const r = await fetchJSON(API.cupomAtivar, {
          method:'POST',
          headers:{ 'Content-Type': 'application/json' },
          body: JSON.stringify({ codigo, code: codigo }) // aceita ambas chaves
        });
        if (r.ok && r.body) {
          cupomState.aplicado = true;
          msg('Cupom aplicado com sucesso! O desconto aparecerá na próxima etapa.', 'msg-ok');
          clearPendingCupom();
        } else if (r.status === 401) {
          msg('Faça login para aplicar o cupom.', 'msg-err');
        } else {
          msg('Não foi possível aplicar. Tente novamente.', 'msg-err');
          $btnAplicar.disabled = false;
        }
      } catch(e){
        msg('Erro de rede ao aplicar. Tente novamente.', 'msg-err');
        $btnAplicar.disabled = false;
      }
    }

    // --- Checkout ---
    async function proceedCheckout(){
      try{
        $btnCheckout.disabled = true;
        $btnCheckout.textContent = 'Preparando…';

        // Se o backend aceitar cupom via querystring e ainda não estiver aplicado,
        // você pode optar por enviar ?cupom=CODIGO. Caso já aplique no perfil, não precisa.
        const codigo = normalizeCode($codigo.value);
        const qs = (!cupomState.aplicado && codigo) ? ('?cupom=' + encodeURIComponent(codigo)) : '';
        const r = await fetchJSON(API.checkout + qs);

        if (r.ok && r.body && (r.body.checkoutUrl || r.body.url || r.body.location)) {
          const url = r.body.checkoutUrl || r.body.url || r.body.location;
          location.href = url;
          return;
        }
        // fallback: permanece nesta mesma página (não vai para admin)
        $btnCheckout.disabled = false;
        $btnCheckout.textContent = 'Seguir para assinatura';
        alert('Não foi possível iniciar a assinatura agora. Tente novamente.');
      } catch(e){
        console.error(e);
        $btnCheckout.disabled = false;
        $btnCheckout.textContent = 'Seguir para assinatura';
        alert('Não foi possível iniciar a assinatura agora. Tente novamente.');
      }
    }

    // Eventos
    $btnValidar.addEventListener('click', validarCupom);
    $btnAplicar.addEventListener('click', aplicarCupom);
    $btnCheckout.addEventListener('click', proceedCheckout);

    document.addEventListener('DOMContentLoaded', load);
  })();
  </script>
