// public/assets/firebase-init.prod.js
// Firebase init (v8) — MEI Robô (produção)
// Requer: firebase-app.js e firebase-auth.js (v8.10.1) já carregados

(function () {
  if (!(window.firebase && firebase.initializeApp)) {
    console.error("[firebase-init] Firebase SDK v8 não encontrado. Verifique a ordem dos <script>.");
    return;
  }

  // ⚠️ CONFIG REAL (Console → Project settings → Web app)
  var firebaseConfig = {
    apiKey: "AIzaSyCjIbIjLOjAa_NyoB3MMLWOdq_rJs432qg",
    authDomain: "mei-robo-prod.firebaseapp.com",
    projectId: "mei-robo-prod",
    storageBucket: "mei-robo-prod.firebasestorage.app",
    messagingSenderId: "161054994911",
    appId: "1:161054994911:web:4a57ad4337d8edf0b5146a"
  };

  // Inicializa SOMENTE o DEFAULT (o login.html cria/usa 'loginApp')
  var app;
  if (!firebase.apps.length) {
    app = firebase.initializeApp(firebaseConfig);
    console.log("[firebase-init] DEFAULT inicializado:", app.options.projectId);
  } else {
    app = firebase.app();
    console.log("[firebase-init] DEFAULT já existia:", app.options.projectId);
  }

  // Diagnóstico rápido
  try {
    var rows = (firebase.apps || []).map(function (a) {
      return { name: a.name, apiKey: a.options && a.options.apiKey };
    });
    console.table(rows);
  } catch (e) {}
})();
