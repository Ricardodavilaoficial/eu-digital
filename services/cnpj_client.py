import re
import requests

def fetch_cnpj_info(cnpj_digits):
    \"\"\"Busca dados públicos de CNPJ e normaliza.

    Retorna dict:
      { "razaoSocial", "nomeFantasia", "cnae", "cnaeDescricao" }
    ou None em erro/timeout/dados ausentes.
    \"\"\"
    try:
        cnpj = re.sub(r"\\D+", "", str(cnpj_digits or ""))
        if len(cnpj) != 14:
            return None

        urls = [
            f"https://publica.cnpj.ws/cnpj/{cnpj}",
            f"https://www.receitaws.com.br/v1/cnpj/{cnpj}",
        ]
        data = None
        for url in urls:
            try:
                r = requests.get(url, timeout=(3, 5))
                if r.status_code == 200:
                    data = r.json()
                    break
            except Exception:
                continue

        if not isinstance(data, dict):
            return None

        def pick(d, *keys, default=""):
            for k in keys:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return default

        razao = pick(data, "razao_social", "razaoSocial", "nome", "razao")
        fantasia = pick(data, "nome_fantasia", "nomeFantasia", "fantasia")

        cnae_code, cnae_desc = "", ""

        est = data.get("estabelecimento") or {}
        atv = est.get("atividade_principal") or {}
        if isinstance(atv, dict):
            cnae_code = (str(atv.get("id") or "")).strip()
            cnae_desc = (atv.get("descricao") or "").strip()

        if not cnae_code:
            lista = data.get("atividade_principal") or []
            if isinstance(lista, list) and lista:
                item0 = lista[0] or {}
                cnae_code = (str(item0.get("code") or "")).strip()
                cnae_desc = (item0.get("text") or "").strip()

        if not razao:
            razao = pick(data, "razaosocial", "empresa")
        if not fantasia and isinstance(est, dict):
            fantasia = (est.get("nome_fantasia") or "").strip()

        if not (razao or fantasia or cnae_code or cnae_desc):
            return None

        return {
            "razaoSocial": razao,
            "nomeFantasia": fantasia,
            "cnae": cnae_code,
            "cnaeDescricao": cnae_desc,
        }
    except Exception:
        return None
