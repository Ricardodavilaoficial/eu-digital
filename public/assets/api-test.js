// public/assets/api-test.js
const BACKEND_BASE = "https://mei-robo-prod.onrender.com";

async function whoAmI(idToken) {
  const res = await fetch(`${BACKEND_BASE}/auth/whoami`, {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${idToken}`
    }
  });
  const data = await res.json().catch(() => ({}));
  return { status: res.status, data };
}

window.MEIROBO = window.MEIROBO || {};
window.MEIROBO.apiTest = { whoAmI };
