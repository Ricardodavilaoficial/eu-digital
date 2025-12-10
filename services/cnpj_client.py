import re
import requests

def fetch_cnpj_info(cnpj_digits):
    """Busca dados públicos de CNPJ e normaliza.

    Retorna dict:
      {
        "razaoSocial",
        "nomeFantasia",
        "cnae",
        "cnaeDescricao",
        "qsa",        # lista de sócios/administradores (quando disponível)
        "simei",      # bloco simei da ReceitaWS (quando disponível)
        "simples",    # bloco simples da ReceitaWS (quando disponível)
        "raw",        # JSON cru completo da ReceitaWS
      }
    ou None em erro/timeout/dados ausentes.
    """
    try:
        cnpj = re.sub(r"\D+", "", str(cnpj_digits or ""))
        if len(cnpj) != 14:
            return None

        # Agora usamos apenas a API pública da ReceitaWS.
        urls = [
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

        # ReceitaWS: "nome" costuma ser a razão social
        razao = pick(data, "razao_social", "razaoSocial", "nome", "razao")
        fantasia = pick(data, "nome_fantasia", "nomeFantasia", "fantasia")

        cnae_code, cnae_desc = "", ""

        # Legado para formato publica.cnpj.ws (não atrapalha se não existir)
        est = data.get("estabelecimento") or {}
        atv = est.get("atividade_principal") or {}
        if isinstance(atv, dict):
            cnae_code = (str(atv.get("id") or "")).strip()
            cnae_desc = (atv.get("descricao") or "").strip()

        # ReceitaWS: lista "atividade_principal"
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

        # NOVO: além dos campos resumidos, devolvemos também qsa, simei, simples e o JSON cru.
        return {
            "razaoSocial": razao,
            "nomeFantasia": fantasia,
            "cnae": cnae_code,
            "cnaeDescricao": cnae_desc,
            "qsa": data.get("qsa") or [],
            "simei": data.get("simei") or {},
            "simples": data.get("simples") or {},
            "raw": data,
        }
    except Exception:
        return None


def _normalize_nome(s: str) -> str:
    """
    Normaliza nome para comparação simples:
    - maiúsculas
    - remove acentos e caracteres especiais básicos
    - comprime espaços
    """
    if not s:
        return ""
    import unicodedata

    s = str(s)
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.upper()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokeniza_nome(s: str):
    """
    Quebra nome em tokens relevantes (>= 3 chars) para "similaridade pobre porém honesta".
    """
    norm = _normalize_nome(s)
    if not norm:
        return set()
    tokens = [t for t in norm.split(" ") if len(t) >= 3]
    return set(tokens)


def avaliar_vinculo_por_nome(info: dict, nome_busca: str) -> dict:
    """
    Recebe o dict retornado por fetch_cnpj_info + um nome de pessoa (responsável),
    e devolve um dict:
      {
        "avaliacao": "EXATO" | "PROVAVEL" | "NAO_ENCONTRADO",
        "fonte": "qsa" | "desconhecida",
        "matches": [lista de nomes que bateram],
      }
    Sem exceção: em qualquer erro, cai em NAO_ENCONTRADO.
    """
    try:
        if not info or not isinstance(info, dict):
            return {
                "avaliacao": "NAO_ENCONTRADO",
                "fonte": "desconhecida",
                "matches": [],
            }

        nome_busca = (nome_busca or "").strip()
        if not nome_busca:
            return {
                "avaliacao": "NAO_ENCONTRADO",
                "fonte": "desconhecida",
                "matches": [],
            }

        tokens_busca = _tokeniza_nome(nome_busca)
        if not tokens_busca:
            return {
                "avaliacao": "NAO_ENCONTRADO",
                "fonte": "desconhecida",
                "matches": [],
            }

        raw = info.get("raw") or {}
        qsa = info.get("qsa") or raw.get("qsa") or []
        if not isinstance(qsa, list):
            qsa = []

        melhores = []
        melhor_score = 0.0

        for socio in qsa:
            nome_socio = (
                socio.get("nome") or
                socio.get("nome_socio") or
                socio.get("nome_socio_razao_social") or
                ""
            )
            if not nome_socio:
                continue

            tokens_socio = _tokeniza_nome(nome_socio)
            if not tokens_socio:
                continue

            inter = tokens_busca & tokens_socio
            if not inter:
                continue

            # score simples: interseção / min(len(busca), len(socio))
            base = float(min(len(tokens_busca), len(tokens_socio))) or 1.0
            score = float(len(inter)) / base

            if score > melhor_score:
                melhor_score = score
                melhores = [nome_socio]
            elif abs(score - melhor_score) < 1e-6:
                melhores.append(nome_socio)

        if melhor_score >= 0.8:
            avaliacao = "EXATO"
        elif melhor_score >= 0.4:
            avaliacao = "PROVAVEL"
        else:
            avaliacao = "NAO_ENCONTRADO"

        return {
            "avaliacao": avaliacao,
            "fonte": "qsa" if qsa else "desconhecida",
            "matches": melhores,
        }
    except Exception:
        return {
            "avaliacao": "NAO_ENCONTRADO",
            "fonte": "erro",
            "matches": [],
        }


def fetch_cnpj_com_vinculo(cnpj_digits, nome_busca: str | None = None) -> dict | None:
    """
    Helper de alto nível: junta fetch_cnpj_info + avaliação de vínculo por nome.

    Retorna None se o CNPJ não for encontrado.
    Caso contrário:
      {
        "info": <retorno do fetch_cnpj_info>,
        "vinculoNome": { ... }  # se nome_busca fornecido
      }
    """
    info = fetch_cnpj_info(cnpj_digits)
    if not info:
        return None

    result = {"info": info}
    if nome_busca:
        result["vinculoNome"] = avaliar_vinculo_por_nome(info, nome_busca)
    return result
