import re
from services.cnpj_client import fetch_cnpj_info

def limpar_cnpj(cnpj: str) -> str:
    return "".join(ch for ch in str(cnpj) if ch.isdigit())

def normalizar_nome(nome: str) -> str:
    if not nome:
        return ""
    return (
        nome.strip()
            .lower()
            .replace("á","a").replace("à","a").replace("ã","a").replace("â","a")
            .replace("é","e").replace("ê","e")
            .replace("í","i")
            .replace("ó","o").replace("õ","o").replace("ô","o")
            .replace("ú","u")
            .replace("ç","c")
    )

def verificar_cnpj_basico(cnpj_raw: str):
    """
    1) Consulta via ReceitaWS (fetch_cnpj_info)
    2) Classifica MEI / não-MEI
    3) Retorna estrutura normalizada para o MEI Robô
    """
    cnpj = limpar_cnpj(cnpj_raw)
    info = fetch_cnpj_info(cnpj)
    if not info:
        return {
            "ok": False,
            "motivo": "nao_encontrado_no_cache",
            "mensagem": "Não consegui consultar automaticamente o CNPJ. Vamos precisar validar manualmente."
        }

    # -------------------------
    # NORMALIZAÇÃO
    # -------------------------
    cnae = info.get("cnae", "")
    razao = info.get("razaoSocial", "")
    fantasia = info.get("nomeFantasia", "")

    # Vamos considerar MEI se vier cnae + não vier simei, mas a API pública às vezes omite o bloco.
    # Por isso deixamos essa parte aberta para a Comercial depois.
    eh_mei = False  # API Pública não garante esse dado

    return {
        "ok": True,
        "cnpj": cnpj,
        "razaoSocial": razao,
        "nomeFantasia": fantasia,
        "cnae": cnae,
        "cnaeDescricao": info.get("cnaeDescricao", ""),
        "ehMEI": eh_mei,  # por enquanto fictício; real quando migrar à API Comercial
        "raw": info,      # JSON cru para usos futuros
    }


def verificar_autoridade(nome_usuario: str, dados_receita_raw: dict):
    """
    Valida se o usuário que está criando a conta é sócio/administrador.
    (para MEI isso não importa, mas para LTDA/EPP sim)
    """
    if not dados_receita_raw:
        return {"autoridade": "desconhecida"}

    nome_user_norm = normalizar_nome(nome_usuario)

    qsa = dados_receita_raw.get("qsa") or []
    if not isinstance(qsa, list):
        return {"autoridade": "desconhecida"}

    for s in qsa:
        nome_socio = normalizar_nome(s.get("nome", ""))
        if nome_socio and nome_socio in nome_user_norm:
            return {
                "autoridade": "valido",
                "qualificacao": s.get("qual", "")
            }

    return {
        "autoridade": "nao_encontrado_no_qsa",
        "mensagem": "O nome informado não aparece no quadro societário. Pode requerer documento adicional."
    }
