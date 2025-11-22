// backend-patch.js — roteia chamadas de API para o backend e injeta token com retry 401
(function () {
  'use strict';

  // ===== Config base/allowlist =====
  const DEFAULT_API = "https://mei-robo-prod.onrender.com";
  const DEV_ALLOW_RE = /^https?:\/\/localhost(?::\d+)?$/i;

  function safeApiBase() {
    try {
      const ov = (window.localStorage && localStorage.getItem('apiBase')) || '';
      if (!ov) return DEFAULT_API;
      const u = new URL(ov, window.location.href);
      // Allowlist: PROD + localhost (dev)
      if (u.origin === DEFAULT_API || DEV_ALLOW_RE.test(u.origin)) return u.origin;
      console.warn('[backend-patch] apiBase override ignorado (fora da allowlist):', u.origin);
      return DEFAULT_API;
    } catch {
      return DEFAULT_API;
    }
  }
  const API_BASE = safeApiBase();
  const API_ORIGIN = (() => { try { return new URL(API_BASE).origin; } catch { return DEFAULT_API; } })();

  // Domínios antigos a redirecionar → backend atual
  const OLD_ORIGINS = [
    "https://eu-digital.onrender.com",
    "http://eu-digital.onrender.com"
  ];

  // Prefixos de API que devem ir ao backend
  const API_PREFIXES = [
    "/auth",
    "/clientes",
    "/pricing",
    "/schedule",
    "/whatsapp",
    "/api",
    "/licencas",
    "/admin",        // garante admin → backend
    "/gerar-cupom",  // tela Admin usa este caminho relativo
    "/__list"        // util interno: listagem (admin)
  ];

  // Mapeamentos específicos (mantido simples — sem rewrite especial)
  function mapPath(path) {
    return path;
  }

  // Recursos locais (não devem ser roteados ao backend)
  const LOCAL_PREFIXES = ["/partials", "/assets"];
  const LOCAL_EXTS = [
    ".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico",
    ".webmanifest", ".json", ".map"
  ];

  function isLocalPath(path) {
    if (!path || !path.startsWith("/")) return false;
    for (const p of LOCAL_PREFIXES) if (path.startsWith(p)) return true;
    for (const ext of LOCAL_EXTS) if (path.endsWith(ext)) return true;
    return false;
  }

  function isApiPath(path) {
    if (!path || !path.startsWith("/")) return false;
    return API_PREFIXES.some(p => path.startsWith(p));
  }

  function rewriteAbsoluteIfOldOrigin(urlStr) {
    try {
      const u = new URL(urlStr, window.location.href);
      if (OLD_ORIGINS.includes(u.origin)) {
        const newPath = mapPath(u.pathname);
        return API_BASE + newPath + (u.search || "");
      }
    } catch {}
    return null;
  }

  // ===== Token helpers =====
  async function getIdTokenSoft() {
    // Tenta Firebase primeiro
    try {
      if (window.firebase && firebase.auth) {
        const cur = firebase.auth().currentUser;
        if (cur) return await cur.getIdToken();
      }
    } catch {}
    // Fallback: localStorage (pode estar recente via refresh manual)
    try {
      const t = localStorage.getItem('idToken');
      if (t && t.includes('.')) return t;
    } catch {}
    return null;
  }

  async function getIdTokenFresh() {
    try {
      if (window.firebase && firebase.auth) {
        const cur = firebase.auth().currentUser;
        if (cur) return await cur.getIdToken(true);
      }
    } catch {}
    return null;
  }

  // Headers utils (aceita Headers|plain|array)
  function toHeaders(initHeaders) {
    try {
      return new Headers(initHeaders || {});
    } catch {
      const h = new Headers();
      if (initHeaders && typeof initHeaders === 'object') {
        Object.entries(initHeaders).forEach(([k, v]) => { if (v != null) h.append(k, String(v)); });
      }
      return h;
    }
  }

  function hasAuthHeader(h) {
    try { return (h.get('Authorization') || h.get('authorization') || '').trim() !== ''; }
    catch { return false; }
  }

  function setIfAbsent(h, key, val) {
    if (!h.has(key)) h.set(key, val);
  }

  // Decide se devemos injetar Authorization: apenas quando destino == API_BASE e path de API
  function shouldAttachAuth(u) {
    try {
      const url = (u instanceof URL) ? u : new URL(u, window.location.href);
      return (url.origin === API_ORIGIN) && isApiPath(url.pathname);
    } catch { return false; }
  }

  // Cria uma Request roteada (URL) preservando tudo
  function routeRequest(reqOrUrl, init) {
    // Normaliza para Request
    const req0 = (typeof reqOrUrl === 'string') ? new Request(reqOrUrl, init) : reqOrUrl;

    let url;
    try { url = new URL(req0.url, window.location.href); } catch { return { req: req0, url: null }; }

    // 1) Absoluta domínio antigo → API_BASE
    if (OLD_ORIGINS.includes(url.origin)) {
      const newPath = mapPath(url.pathname);
      const newUrl = API_BASE + newPath + (url.search || "");
      return { req: new Request(newUrl, req0), url: new URL(newUrl) };
    }

    // 2) Mesma origem com caminho local → mantém
    const sameOrigin = url.origin === window.location.origin;

    if (sameOrigin) {
      const path = url.pathname || '/';
      if (isLocalPath(path)) return { req: req0, url };

      if (isApiPath(path)) {
        const newPath = mapPath(path);
        const newUrl = API_BASE + newPath + (url.search || "");
        return { req: new Request(newUrl, req0), url: new URL(newUrl) };
      }
    }

    // 3) Caminho absoluto já no API_BASE → mantém (ainda assim podemos injetar auth)
    if (url.origin === API_ORIGIN) return { req: req0, url };

    // 4) Caminho relativo string (ex.: "/api/x") quando veio por string
    if (typeof reqOrUrl === 'string' && reqOrUrl.startsWith('/')) {
      const p = reqOrUrl;
      if (isLocalPath(p)) return { req: req0, url: new URL(req0.url, window.location.href) };
      if (isApiPath(p)) {
        const newUrl = API_BASE + mapPath(p);
        // Nesse caso usamos init (se houve) em cima da string original
        return { req: new Request(newUrl, init || {}), url: new URL(newUrl) };
      }
    }

    // 5) Absoluta de domínio antigo (string)
    if (typeof reqOrUrl === 'string') {
      const rew = rewriteAbsoluteIfOldOrigin(reqOrUrl);
      if (rew) return { req: new Request(rew, init || {}), url: new URL(rew) };
    }

    // 6) Outras URLs/terceiros → passa direto
    return { req: req0, url };
  }

  // Monta uma nova Request com cabeçalhos ajustados
  function withHeaders(baseReq, headersObj) {
    const h = toHeaders(headersObj);
    return new Request(baseReq, { headers: h, method: baseReq.method });
  }

  // Sinaliza estado para inspeção eventual
  try { window.__backendPatch = { apiBase: API_BASE, applied: true }; } catch {}

  const origFetch = window.fetch.bind(window);

  window.fetch = (resource, init) => {
    const exec = async () => {
      try {
        // Reescrita de URL (roteamento) primeiro
        const routed = routeRequest(resource, init);
        let reqBase = routed.req;
        const url = routed.url; // pode ser null em casos extremos

        // Se o recurso original era string absoluta de domínio antigo (caso 1 acima), já reescrevemos.
        // Se for string nova (API), também já virou Request.

        // Cabeçalhos atuais (sempre clonar para não mutar)
        let headers = toHeaders(reqBase.headers);

        // UX/diagnóstico mínimo
        setIfAbsent(headers, 'Accept-Language', 'pt-BR');

        // Tenta injetar Authorization quando apropriado e ausente
        let injectedAuth = false;
        if (url && shouldAttachAuth(url) && !hasAuthHeader(headers)) {
          const tok = await getIdTokenSoft();
          if (tok) {
            headers.set('Authorization', 'Bearer ' + tok);
            injectedAuth = true;
          }
        }

        // Request 1 (com headers finais)
        let req1 = withHeaders(reqBase, headers);

        // Dispara
        let resp = await origFetch(req1);

        // Retry 401: apenas se nós injetamos o token (para não atropelar chamadas do app)
        if (resp && resp.status === 401 && injectedAuth) {
          const fresh = await getIdTokenFresh();
          if (fresh) {
            const h2 = toHeaders(reqBase.headers);
            h2.set('Authorization', 'Bearer ' + fresh);
            setIfAbsent(h2, 'Accept-Language', 'pt-BR');
            const req2 = withHeaders(reqBase, h2);
            try { resp = await origFetch(req2); } catch (e) { /* mantém resp anterior */ }
          }
        }

        return resp;
      } catch (e) {
        // Em caso de erro inesperado, delega ao fetch original sem patch
        try { return await origFetch(resource, init); }
        catch { throw e; }
      }
    };
    return exec();
  };
})();
