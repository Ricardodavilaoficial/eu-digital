// Firebase init (v8 ou v9-compat) — MEI Robô (produção)
// Requer: (a) v8: firebase-app.js + firebase-auth.js (+ firebase-firestore.js se usar Firestore)
//      ou (b) v9 compat: firebase-app-compat.js + firebase-auth-compat.js (+ firebase-firestore-compat.js se usar Firestore)
// Este script inicializa SOMENTE o app DEFAULT (login.html pode criar 'loginApp').

(function () {
  'use strict';

  // ---- CONFIG REAL (Console → Project settings → Web app)
  var firebaseConfig = {
    apiKey: "AIzaSyCjIbIjLOjAa_NyoB3MMLWOdq_rJs432qg",
    authDomain: "mei-robo-prod.firebaseapp.com",
    projectId: "mei-robo-prod",
    // OBS: storageBucket correto para uso de Storage: *.appspot.com
    storageBucket: "mei-robo-prod.appspot.com",
    messagingSenderId: "161054994911",
    appId: "1:161054994911:web:4a57ad4337d8edf0b5146a"
  };

  // ===== Blindagem extra =====
  function deepFreeze(o){ try{ Object.freeze(o); Object.keys(o||{}).forEach(function(k){ if (o[k] && typeof o[k]==='object') deepFreeze(o[k]); }); }catch{} }
  function maskKey(k){ if(!k || typeof k!=='string') return ''; if(k.length<=6) return '***'; return k.slice(0,3)+'***'+k.slice(-3); }
  function validConfig(cfg){
    return cfg && typeof cfg==='object'
      && typeof cfg.apiKey==='string' && cfg.apiKey && cfg.apiKey.toUpperCase()!=='PASTE_API_KEY'
      && typeof cfg.projectId==='string' && cfg.projectId
      && typeof cfg.appId==='string' && cfg.appId
      && typeof cfg.authDomain==='string' && cfg.authDomain;
  }
  deepFreeze(firebaseConfig);

  // Espera o Firebase estar disponível (caso os <script> anteriores carreguem ligeiramente depois)
  var MAX_TRIES = 20;     // ~2s (20 * 100ms)
  var TRY_DELAY = 100;

  function haveFirebase() {
    return !!(window.firebase && typeof firebase.initializeApp === 'function');
  }

  function warnCompatMixing(){
    try{
      var hasCompat = !!(window.firebase && firebase.SDK_VERSION && /-compat/.test(firebase.SDK_VERSION));
      var hasV8 = !!(window.firebase && firebase.SDK_VERSION && !/-compat/.test(firebase.SDK_VERSION));
      if (hasCompat && hasV8) console.warn('[firebase-init] Mistura de SDKs detectada (compat + v8). Prefira um só.');
    }catch{}
  }

  function initDefault() {
    try {
      if (!validConfig(firebaseConfig)) {
        console.error('[firebase-init] Config inválida — verifique as credenciais do app web.');
        return;
      }

      warnCompatMixing();

      var app;
      if (!firebase.apps || !firebase.apps.length) {
        app = firebase.initializeApp(firebaseConfig);
        try { console.log("[firebase-init] DEFAULT inicializado:", (app.options && app.options.projectId) || "(?)"); } catch {}
      } else {
        app = firebase.app();
        try { console.log("[firebase-init] DEFAULT já existia:", (app.options && app.options.projectId) || "(?)"); } catch {}
      }

      // Expõe auth (se pacote de auth estiver carregado)
      if (typeof firebase.auth === 'function') {
        try {
          var auth = firebase.auth();
          if (typeof auth.useDeviceLanguage === 'function') auth.useDeviceLanguage();
          try { Object.defineProperty(window, '_auth', { value: auth, writable: false, configurable: false }); }
          catch { window._auth = auth; }
        } catch (e) {
          console.warn("[firebase-init] firebase.auth() não pôde ser obtido:", e);
        }
      } else {
        console.warn("[firebase-init] Carregue 'firebase-auth.js' (v8) ou 'firebase-auth-compat.js' (v9 compat).");
      }

      // Diagnóstico (opcional): DEBUG_FIREBASE=1 no localStorage para ver tabela
      try {
        var debug = (function(){ try { return localStorage.getItem('DEBUG_FIREBASE')==='1'; } catch { return false; } })();
        if (debug && (firebase.apps || []).length) {
          var rows = (firebase.apps || []).map(function (a) {
            var k = a && a.options && a.options.apiKey;
            return { name: a && a.name, apiKeyMasked: maskKey(String(k||'')), projectId: a && a.options && a.options.projectId };
          });
          if (rows && rows.length) console.table(rows);
        }
      } catch (_) {}

      try {
        window.__firebaseProject = {
          projectId: (app && app.options && app.options.projectId) || null,
          appId:     (app && app.options && app.options.appId) || null,
          hasAuth:   (typeof firebase.auth === 'function'),
          hasFS:     (typeof firebase.firestore === 'function')
        };
      } catch {}

    } catch (err) {
      console.error("[firebase-init] Falha ao inicializar o app DEFAULT:", err);
    }
  }

  (function waitForFirebase(tries) {
    if (haveFirebase()) { initDefault(); return; }
    if (tries >= MAX_TRIES) {
      console.error(
        "[firebase-init] Firebase não disponível após aguardar.",
        "Carregue ANTES deste arquivo:",
        " - v8: firebase-app.js + firebase-auth.js (+ firebase-firestore.js se necessário)",
        " - ou v9 compat: firebase-app-compat.js + firebase-auth-compat.js (+ firebase-firestore-compat.js se necessário)"
      );
      return;
    }
    setTimeout(function () { waitForFirebase(tries + 1); }, TRY_DELAY);
  })(0);
})();
