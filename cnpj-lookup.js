
/**
 * cnpj-lookup.js — helper opcional (frontend)
 * Uso sugerido:
 *   attachCnpjLookup({
 *     endpoint: "/integracoes/cnpj",
 *     inputSelector: "#campo-cnpj",
 *     buttonSelector: "#btn-buscar-cnpj",
 *     nomeSelector: "#campo-nome-responsavel", // opcional (para heurística)
 *     onFill: (data) => { /* preencha seus inputs aqui */ /*}
 *   });
 */
export function attachCnpjLookup(opts) {
  const {
    endpoint = "/integracoes/cnpj",
    inputSelector,
    buttonSelector,
    nomeSelector,
    onFill
  } = opts || {};

  const $cnpj = document.querySelector(inputSelector);
  const $btn = document.querySelector(buttonSelector);
  const $nome = nomeSelector ? document.querySelector(nomeSelector) : null;

  if (!$cnpj || !$btn) return;

  async function fetchAndFill() {
    const raw = ($cnpj.value || "").replace(/\D+/g, "");
    if (!/^\d{14}$/.test(raw)) {
      alert("CNPJ inválido. Digite 14 dígitos.");
      return;
    }
    const params = new URLSearchParams();
    if ($nome && $nome.value) params.set("nome", $nome.value);

    $btn.disabled = true;
    try {
      const res = await fetch(`${endpoint}/${raw}?${params.toString()}`, { method: "GET" });
      const ok = res.ok;
      const data = await res.json().catch(() => ({}));
      if (!ok) {
        alert(data?.erro || "Falha ao consultar CNPJ.");
        return;
      }
      if (typeof onFill === "function") onFill(data);
    } catch (e) {
      alert("Indisponível no momento. Tente novamente em instantes.");
    } finally {
      $btn.disabled = false;
    }
  }

  $btn.addEventListener("click", (e) => {
    e.preventDefault();
    fetchAndFill();
  });
}
