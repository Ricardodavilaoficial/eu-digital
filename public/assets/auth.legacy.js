// public/assets/auth.js
// Inicializa Firebase Auth e expõe uma função para logar e obter ID Token

window.MEIROBO = window.MEIROBO || {};

// Configuração oficial do seu app Web no Firebase
const firebaseConfig = {
  apiKey: "AIzaSyCjIbIjLOjAa_NyoB3MMLWOdq_rJs432qg",
  authDomain: "mei-robo-prod.firebaseapp.com",
  projectId: "mei-robo-prod",
  storageBucket: "mei-robo-prod.firebasestorage.app",
  messagingSenderId: "161054994911",
  appId: "1:161054994911:web:4a57ad4337d8edf0b5146a"
};

// Inicializa Firebase (compat)
if (!firebase.apps || !firebase.apps.length) {
  firebase.initializeApp(firebaseConfig);
}

const auth = firebase.auth();

// Faz login por email/senha e retorna o ID Token
async function loginAndGetIdToken(email, password) {
  const cred = await auth.signInWithEmailAndPassword(email, password);
  const user = cred.user;
  if (!user) throw new Error("No user");
  return await user.getIdToken(true);
}

// Exponha globalmente
window.MEIROBO.auth = { loginAndGetIdToken };
