// signed-url.js — MEI Robô: previews seguros com Signed URL (Firebase v9 modular)

const FN_BASE = "https://api-aiwaw34poq-rj.a.run.app";

// Cache simples em memória: path -> { url, expiresAt }
const cache = new Map();

async function getAuthAndUser() {
  const { initializeApp, getApps } = await import("https://www.gstatic.com/firebasejs/9.23.0/firebase-app.js");
  const { getAuth, onAuthStateChanged } = await import("https://www.gstatic.com/firebasejs/9.23.0/firebase-auth.js");

  let app = getApps()[0];
  if (!app) {
    const init = await fetch("/__/firebase/init.json").then(r => r.json());
    const cfg = init.firebaseConfig || init;
    app = initializeApp(cfg);
  }
  const auth = getAuth(app);

  const user = await new Promise(resolve => {
    const off = onAuthStateChanged(auth, u => { off(); resolve(u || null); });
  });
  if (!user) throw new Error("not_logged_in");
  return { auth, user };
}

async function getSignedUrl(path) {
  // cache válido?
  const hit = cache.get(path);
  const now = Date.now() + 5000; // folga de 5s
  if (hit && hit.expiresAt > now) return hit.url;

  const { user } = await getAuthAndUser();
  const idToken = await user.getIdToken();

  const url = `${FN_BASE}/media/signed-url?path=${encodeURIComponent(path)}`;
  const resp = await fetch(url, { headers: { Authorization: "Bearer " + idToken } });
  const json = await resp.json();
  if (!resp.ok || !json.url) {
    const err = new Error(json?.error || "signed_url_failed");
    err.httpStatus = resp.status;
    throw err;
  }

  cache.set(path, { url: json.url, expiresAt: json.expiresAt || (Date.now() + 14 * 60 * 1000) });
  return json.url;
}

/**
 * Converte elementos com data-signed-src em previews seguros
 * Suporta:
 *  - <img data-signed-src="users/<uid>/media/.../file.jpg">
 *  - <video data-signed-src="..."> (coloca .src e dá .load())
 *  - <a data-signed-src="..."> (vira link)
 *  - <embed>/<iframe data-signed-src="..."> (PDF/visualização)
 */
export async function initSignedPreviews(root = document) {
  const nodes = root.querySelectorAll("[data-signed-src]");
  if (!nodes.length) return;

  for (const el of nodes) {
    const path = el.getAttribute("data-signed-src");
    if (!path) continue;

    try {
      const signed = await getSignedUrl(path);

      if (el.tagName === "IMG") {
        el.loading = el.getAttribute("loading") || "lazy";
        el.decoding = el.getAttribute("decoding") || "async";
        el.src = signed;
      } else if (el.tagName === "VIDEO") {
        const source = el.querySelector("source") || el;
        source.src = signed;
        el.controls = true;
        el.load();
      } else if (el.tagName === "A") {
        el.href = signed;
        el.target = el.getAttribute("target") || "_blank";
        el.rel = el.getAttribute("rel") || "noopener";
      } else if (el.tagName === "EMBED" || el.tagName === "IFRAME") {
        el.src = signed;
      } else {
        // fallback: background-image
        el.style.backgroundImage = `url("${signed}")`;
      }

      el.dataset.signedReady = "1";
      el.removeAttribute("data-signed-error");
    } catch (e) {
      el.dataset.signedError = e.httpStatus || e.message || "error";
      if (el.tagName === "IMG") el.alt = el.alt || "preview indisponível";
    }
  }
}

// Utilidade exportada caso precise pedir uma URL assinada manualmente
export { getSignedUrl };
