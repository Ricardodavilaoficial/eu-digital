(function () {
  const form = document.getElementById("login-form");
  const emailEl = document.getElementById("email");
  const passEl = document.getElementById("password");
  const msgEl  = document.getElementById("login-msg");

  function setMsg(text, ok=false) {
    if (!msgEl) return;
    msgEl.textContent = text;
    msgEl.style.color = ok ? "#065f46" : "#7f1d1d";
  }

  async function doLogin(email, password) {
    const auth = window.loginAuth || (window.firebase && firebase.auth(firebase.app("loginApp")));
    if (!auth) {
      console.error("[login] Auth não disponível (loginApp).");
      setMsg("Erro interno: Auth indisponível.", false);
      return;
    }
    try {
      console.log("[login] Tentando login…");
      setMsg("Autenticando…");
      const cred = await auth.signInWithEmailAndPassword(email, password);
      console.log("[login] OK, uid:", cred.user?.uid);
      setMsg("✅ Login OK.", true);

      // Diagnóstico extra (sem expor token)
      console.log("[login] user:", {
        uid: cred.user?.uid,
        email: cred.user?.email
      });
    } catch (err) {
      console.error("[login] Falha:", err);
      // Mensagens mais claras
      if (err?.code === "auth/invalid-api-key") {
        setMsg("Falha: API key inválida (verifique firebase-init.js).", false);
      } else if (err?.code === "auth/invalid-email") {
        setMsg("E-mail inválido.", false);
      } else if (err?.code === "auth/user-not-found" || err?.code === "auth/wrong-password") {
        setMsg("E-mail ou senha incorretos.", false);
      } else {
        setMsg("Falha no login: " + (err?.message || "erro desconhecido"), false);
      }
    }
  }

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      const email = emailEl.value.trim();
      const pass  = passEl.value;
      if (!email || !pass) {
        setMsg("Preencha e-mail e senha.", false);
        return;
      }
      doLogin(email, pass);
    });
  }

  // Log de apps no carregamento (confere que apiKeys estão iguais)
  try {
    if (window.firebase?.apps) {
      console.table(firebase.apps.map(a => ({ name: a.name, apiKey: a.options.apiKey })));
    }
  } catch {}
})();
