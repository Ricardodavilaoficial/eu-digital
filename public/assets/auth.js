// public/assets/auth.js — STUB SEGURO
// Usa o app já inicializado por /assets/firebase-init.js e NÃO reinicializa nada.
(function () {
  window.MEIROBO = window.MEIROBO || {};

  if (!window.firebase || !firebase.apps || !firebase.apps.length) {
    console.warn('auth.js: Firebase não inicializado (ok para ignorar se esta página não usa Auth).');
    window.MEIROBO.auth = {
      loginAndGetIdToken: async () => { throw new Error('firebase-not-initialized'); },
      logout: async () => {}
    };
    return;
  }

  const auth = firebase.auth();

  async function loginAndGetIdToken(email, password) {
    const cred = await auth.signInWithEmailAndPassword(email, password);
    const user = cred.user;
    if (!user) throw new Error('no-user');
    return await user.getIdToken(true);
  }

  async function logout() {
    await auth.signOut();
  }

  window.MEIROBO.auth = { loginAndGetIdToken, logout };
})();
