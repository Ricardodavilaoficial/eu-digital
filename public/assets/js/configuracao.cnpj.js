// configuracao.cnpj.js — autofill robusto do CNPJ (compatível com {ok,true,data:{...}})
// Usa window.API_BASE se definido; caso contrário, usa caminhos relativos.

(function () {
  const API = window.API_BASE || "";

  async function jfetch(url) {
    const r = await fetch(url, { credentials: "include" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  const onlyDigits = (s) => String(s || "").replace(/\D+/g, "");
  const setVal = (idOrName, v) => {
    if (v == null) return;
    let el = document.getElementById(idOrName) || document.querySelector(`[name="${idOrName}"]`);
    if (el && "value" in el) el.value = v;
  };
  const setTxt = (idOrName, v) => {
    if (v == null) return;
    let el = document.getElementById(idOrName) || document.querySelector(`[name="${idOrName}"]`);
    if (el) el.textContent = v;
  };
  const setEither = (idOrName, v) => {
    let el = document.getElementById(idOrName) || document.querySelector(`[name="${idOrName}"]`);
    if (!el || v == null) return;
    if ("value" in el) el.value = v;
    else el.textContent = v;
  };

  async function preencherCNPJ() {
    try {
      const params = new URLSearchParams(location.search);
      const uid = params.get("uid") || window.__CURRENT_UID__;
      if (!uid) return;

      // 1) Configuração do profissional
      const cfg = await jfetch(`${API}/api/configuracao?uid=${encodeURIComponent(uid)}`).catch(() => null);
      const cnpjDigits = onlyDigits(cfg?.data?.cnpj || "");
      if (!cnpjDigits || cnpjDigits.length !== 14) return;

      // espelha o CNPJ no input, se existir
      setEither("cnpj", cnpjDigits);

      // 2) Dados oficiais do CNPJ
      const info = await jfetch(`${API}/api/cnpj/${cnpjDigits}`).catch(() => null);
      if (!info) return;
      const c = info.data || info || {}; // compat: aceita {data:{...}} ou {...}

      // 3) Campos principais
      setVal("razaoSocial", c.razaoSocial || c.legal_name || "");
      setVal("nomeFantasia", c.nomeFantasia || c.trade_name || "");

      // CNAE (tanto em value quanto texto — depende de como está no HTML)
      const cnaeCode = c.cnae || c.cnaePrincipal?.codigo || "";
      const cnaeDesc = c.cnaeDescricao || c.cnaePrincipal?.descricao || "";
      setEither("cnae", cnaeCode);
      setEither("cnaeDescricao", cnaeDesc);

      // 4) Endereço — preenche campos separados se existirem, ou monta "endereco" único
      const end = c.endereco || c.address || {};
      const logradouro = end.logradouro || end.street || "";
      const numero = end.numero || end.number || "";
      const bairro = end.bairro || end.district || "";
      const cidade = end.cidade || end.municipio || end.city || "";
      const uf = end.uf || end.state || "";
      const cep = onlyDigits(end.cep || end.zip || "");

      // separados (se existirem na página)
      setVal("logradouro", logradouro);
      setVal("numero", numero);
      setVal("bairro", bairro);
      setVal("cidade", cidade);
      setVal("uf", uf);
      setVal("cep", cep);

      // campo único "endereco" (mantém compat com teu HTML atual)
      const enderecoCompacto = [logradouro, numero, bairro, cidade && (cidade + (uf ? "/" + uf : ""))]
        .filter(Boolean)
        .join(", ");
      setVal("endereco", enderecoCompacto);

      console.log("[CNPJ] Autofill concluído.");
    } catch (e) {
      console.warn("[CNPJ] erro ao preencher", e);
    }
  }

  document.addEventListener("DOMContentLoaded", preencherCNPJ);
})();
