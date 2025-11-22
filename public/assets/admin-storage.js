/* admin-storage.js — MEI Robô
 * Página de administração para listar arquivos de Storage e gerar Signed URL (15 min).
 * Requisitos:
 *  - /assets/firebase-init.js com config do Firebase (app compat)
 *  - Usuário autenticado (guard simples abaixo)
 *  - Backend com endpoint /api/storage/signed-url (fallback /storage/signed-url)
 */

(function(){
  const auth = firebase.auth();
  const storage = firebase.storage();

  const $ = (sel)=>document.querySelector(sel);
  const uidInput = $("#uid");
  const yearSel = $("#year");
  const monthSel = $("#month");
  const daySel = $("#day");
  const statusEl = $("#status");
  const filesTbody = $("#filesTbody");

  const today = new Date();
  function pad2(n){ return String(n).padStart(2,'0'); }

  function initSelectors(){
    const thisY = today.getFullYear();
    for (let y = thisY - 3; y <= thisY + 1; y++){
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = String(y);
      if (y === thisY) opt.selected = true;
      yearSel.appendChild(opt);
    }
    for (let m = 1; m <= 12; m++){
      const opt = document.createElement("option");
      opt.value = pad2(m);
      opt.textContent = pad2(m);
      if (m === (today.getMonth()+1)) opt.selected = true;
      monthSel.appendChild(opt);
    }
    for (let d = 1; d <= 31; d++){
      const opt = document.createElement("option");
      opt.value = pad2(d);
      opt.textContent = pad2(d);
      if (d === today.getDate()) opt.selected = true;
      daySel.appendChild(opt);
    }
  }

  async function guard(){
    return new Promise((resolve)=>{
      auth.onAuthStateChanged(async (user)=>{
        if(!user){
          // não logado → enviar para login
          statusEl.textContent = "Não autenticado. Redirecionando para login...";
          setTimeout(()=> location.href = "/pages/login.html", 600);
          return;
        }
        // tenta ler claim admin (best-effort)
        try{
          const token = await user.getIdTokenResult();
          if(!token.claims || token.claims.admin !== true){
            statusEl.innerHTML = "Você está autenticado, mas não é admin. Esta página é restrita.";
          } else {
            statusEl.innerHTML = "Autenticado como admin.";
          }
        }catch(e){
          console.warn("Falha ao checar claims", e);
        }
        resolve(user);
      });
    });
  }

  async function listFiles(){
    const uid = uidInput.value.trim();
    if(!uid){ alert("Informe o UID ou clique em 'Usar meu UID'"); return; }
    const basePath = `users/${uid}/media/${yearSel.value}/${monthSel.value}/${daySel.value}`;
    statusEl.textContent = `Listando: ${basePath} ...`;

    const ref = storage.ref(basePath);
    filesTbody.innerHTML = `<tr><td colspan="4" class="muted">Carregando...</td></tr>`;

    try {
      const res = await ref.listAll();
      if(res.items.length === 0){
        filesTbody.innerHTML = `<tr><td colspan="4" class="muted">Sem arquivos neste dia.</td></tr>`;
        return;
      }

      filesTbody.innerHTML = "";
      for (const itemRef of res.items){
        const meta = await itemRef.getMetadata().catch(()=>({ size: 0 }));
        const tr = document.createElement("tr");
        const nameTd = document.createElement("td");
        nameTd.textContent = itemRef.name;

        const sizeTd = document.createElement("td");
        const size = meta.size || 0;
        const sizeKB = (size/1024).toFixed(1) + " KB";
        sizeTd.textContent = size < 1024 ? size+" B" : sizeKB;

        const pathTd = document.createElement("td");
        const fullPath = itemRef.fullPath;
        pathTd.className = "small";
        pathTd.textContent = fullPath;

        const actionsTd = document.createElement("td");
        actionsTd.className = "actions";
        const openBtn = document.createElement("button");
        openBtn.textContent = "Abrir (Signed URL)";
        openBtn.addEventListener("click", ()=> openSignedUrl(fullPath));
        actionsTd.appendChild(openBtn);

        tr.appendChild(nameTd);
        tr.appendChild(sizeTd);
        tr.appendChild(pathTd);
        tr.appendChild(actionsTd);
        filesTbody.appendChild(tr);
      }

      statusEl.innerHTML = `Pronto. <span class="ok">Arquivos listados.</span>`;
    } catch(e){
      console.error(e);
      statusEl.innerHTML = `<span class="err">Falhou listar: ${e.message || e}</span>`;
      filesTbody.innerHTML = `<tr><td colspan="4" class="muted">Erro ao listar.</td></tr>`;
    }
  }

  async function openSignedUrl(path){
    statusEl.textContent = "Gerando Signed URL...";
    const user = auth.currentUser;
    if(!user){ alert("Faça login novamente."); return; }
    const idToken = await user.getIdToken(true);

    const tryFetch = async (url)=>{
      const q = new URLSearchParams({ path });
      const resp = await fetch(`${url}?${q}`, {
        headers: { "Authorization": `Bearer ${idToken}` }
      });
      if(!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      return resp.json();
    };

    try{
      // tenta /api/... depois /...
      let data;
      try {
        data = await tryFetch("/api/storage/signed-url");
      } catch(e1){
        data = await tryFetch("/storage/signed-url");
      }
      if(!data || !data.url){
        throw new Error("Resposta sem URL");
      }
      window.open(data.url, "_blank","noopener");
      statusEl.innerHTML = `URL gerada. <span class="muted">Expira em ~15min.</span>`;
    }catch(e){
      console.error(e);
      statusEl.innerHTML = `<span class="err">Falhou gerar Signed URL: ${e.message || e}</span>`;
    }
  }

  function wire(){
    $("#useMyUid").addEventListener("click", async ()=>{
      const user = auth.currentUser;
      if(!user) return alert("Não autenticado.");
      uidInput.value = user.uid;
    });
    $("#listBtn").addEventListener("click", listFiles);
  }

  // boot
  initSelectors();
  guard().then(()=> wire());
})();
