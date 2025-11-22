// public/assets/cookies.js
(function () {
  if (window.__cookieConsentLoaded) return;
  window.__cookieConsentLoaded = true;

  const STORE_KEY = 'cookieConsent';
  const VERSION = 1;

  function getConsent() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || typeof data !== 'object') return null;
      return data;
    } catch { return null; }
  }

  function saveConsent(opts) {
    const data = {
      v: VERSION,
      ts: Date.now(),
      analytics: !!opts.analytics,
      marketing: !!opts.marketing
    };
    localStorage.setItem(STORE_KEY, JSON.stringify(data));
    window.cookieConsent = data;
    document.dispatchEvent(new CustomEvent('cookie-consent-changed', { detail: data }));
  }

  function createBanner() {
    const el = document.createElement('div');
    el.className = 'cookie-banner';
    el.innerHTML = `
      <div class="cookie-banner__inner container">
        <div class="cookie-banner__text">
          Usamos cookies para operar o site (essenciais) e, com seu consentimento, para
          <strong>métricas</strong> e <strong>marketing</strong>. Você pode aceitar todos, rejeitar
          não-essenciais ou definir preferências.
        </div>
        <div class="cookie-banner__actions">
          <button type="button" class="btn btn--ghost" data-cc="reject">Rejeitar não-essenciais</button>
          <button type="button" class="btn btn--ghost" data-cc="prefs">Preferências</button>
          <button type="button" class="btn btn--primary" data-cc="accept">Aceitar todos</button>
        </div>
      </div>
    `;
    document.body.appendChild(el);
    return el;
  }

  function createModal() {
    const wrap = document.createElement('div');
    wrap.className = 'cookie-modal';
    wrap.innerHTML = `
      <div class="cookie-backdrop" data-cc="close"></div>
      <div class="cookie-modal__card" role="dialog" aria-modal="true" aria-labelledby="cookieModalTitle">
        <h3 id="cookieModalTitle">Preferências de cookies</h3>
        <p class="cookie-modal__desc">Escolha como o MEI Robô pode usar cookies além dos essenciais.</p>

        <div class="cookie-option">
          <label class="cookie-option__row">
            <input type="checkbox" checked disabled />
            <div>
              <strong>Essenciais (sempre ativos)</strong>
              <div class="hint">Necessários para o funcionamento básico do site.</div>
            </div>
          </label>
        </div>

        <div class="cookie-option">
          <label class="cookie-option__row">
            <input id="cc-analytics" type="checkbox" />
            <div>
              <strong>Métricas (analytics)</strong>
              <div class="hint">Ajudam a entender uso e melhorar a experiência.</div>
            </div>
          </label>
        </div>

        <div class="cookie-option">
          <label class="cookie-option__row">
            <input id="cc-marketing" type="checkbox" />
            <div>
              <strong>Marketing</strong>
              <div class="hint">Permitem personalizar campanhas e mensurar resultados.</div>
            </div>
          </label>
        </div>

        <div class="cookie-modal__actions">
          <button type="button" class="btn btn--ghost" data-cc="close">Cancelar</button>
          <button type="button" class="btn btn--primary" data-cc="save">Salvar preferências</button>
        </div>
      </div>
    `;
    document.body.appendChild(wrap);
    return wrap;
  }

  // UI
  let bannerEl = null;
  let modalEl = null;

  function openPrefs() {
    const c = getConsent();
    if (!modalEl) modalEl = createModal();
    const a = modalEl.querySelector('#cc-analytics');
    const m = modalEl.querySelector('#cc-marketing');
    a.checked = !!(c && c.analytics);
    m.checked = !!(c && c.marketing);
    modalEl.classList.add('is-open');
  }
  function closePrefs() { if (modalEl) modalEl.classList.remove('is-open'); }
  function hideBanner() { if (bannerEl) bannerEl.remove(); bannerEl = null; }

  // Delegação de eventos (banner + modal + links do rodapé)
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const act = t.getAttribute('data-cc');

    if (t.id === 'manageCookiesLink' || t.closest('[data-action="manage-cookies"]')) {
      e.preventDefault();
      openPrefs();
      return;
    }

    if (act === 'accept') {
      saveConsent({ analytics: true, marketing: true });
      hideBanner(); closePrefs();
    } else if (act === 'reject') {
      saveConsent({ analytics: false, marketing: false });
      hideBanner(); closePrefs();
    } else if (act === 'prefs') {
      openPrefs();
    } else if (act === 'close') {
      closePrefs();
    } else if (act === 'save') {
      const a = modalEl.querySelector('#cc-analytics').checked;
      const m = modalEl.querySelector('#cc-marketing').checked;
      saveConsent({ analytics: a, marketing: m });
      hideBanner(); closePrefs();
    }
  });

  // Inicialização
  document.addEventListener('DOMContentLoaded', () => {
    const c = getConsent();
    if (!c) {
      bannerEl = createBanner();
      window.cookieConsent = null;
    } else {
      window.cookieConsent = c;
    }

    // Exemplo: quando integrar analytics/ads, você pode ouvir este evento
    // document.addEventListener('cookie-consent-changed', ({detail}) => {
    //   if (detail.analytics) { /* carregar seu GA/Matomo */ }
    //   if (detail.marketing) { /* carregar Meta Ads/Google Ads */ }
    // });
  });

  // API pública mínima (para a página cookies.html abrir o modal)
  window.CookieConsent = {
    openPreferences: openPrefs,
    state: () => getConsent()
  };
})();
