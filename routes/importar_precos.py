# routes/importar_precos.py
# Importa uma tabela de preços (CSV/XLSX), normaliza e salva em:
#   profissionais/{uid}/precos
# Aceita colunas flexíveis: nome / descrição / produto / serviço
#                           preco / preço / valor
#                           duracao / duração / tempo / minutos
# Permite números BR (R$, vírgula decimal) e várias formas de duração.

from flask import Blueprint, request, jsonify
from services import db as dbsvc
import pandas as pd
import re

importar_bp = Blueprint('importar_precos', __name__)

# MIMEs mais comuns para uploads
_ALLOWED_MIMES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # browsers variam
}


# ------------ Utilidades de parsing/normalização ------------

def _infer_columns(columns):
    """Mapeia colunas flexivelmente para nome, preco, duracao."""
    cols = {str(c).strip().lower(): c for c in columns}

    def pick(*opts):
        for o in opts:
            if o in cols:
                return cols[o]
        return None

    c_nome = pick("nome", "serviço", "servico", "descricao", "descrição", "produto", "item", "serviços", "servicos")
    c_preco = pick("preco", "preço", "valor", "preço (r$)", "preco (r$)")
    c_dur = pick("duracao", "duração", "tempo", "minutos", "duração (min)", "duracao (min)", "tempo (min)")

    return c_nome, c_preco, c_dur


def _parse_price(val):
    """Converte valores como 'R$ 1.234,56' ou '1,99' para float (BR).
    Retorna 0.0 se não conseguir converter."""
    if val is None:
        return 0.0
    s = str(val).strip()
    if s == "":
        return 0.0
    # Remove moeda e espaços
    s = re.sub(r"[^\d,.\-]", "", s)  # mantém dígitos, vírgula, ponto e sinal
    # Se houver vírgula e ponto, presume-se formato 1.234,56 (BR)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def _parse_duration_to_minutes(val):
    """Aceita: '90', '1:30', '01:30', '1h30', '1h', '45m', '1 hora', '30 min' etc."""
    if val is None:
        return 30
    s = str(val).strip().lower()
    if s == "":
        return 30

    # 1) Formato HH:MM
    m = re.match(r"^\s*(\d{1,2})[:hH](\d{1,2})\s*$", s)
    if m:
        h = int(m.group(1))
        mm = int(m.group(2))
        return max(1, h * 60 + mm)

    # 2) Somente horas: "1h", "2 hora(s)"
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*h(oras?)?\s*$", s)
    if m:
        # suporte a '1,5h'
        h = float(m.group(1).replace(",", "."))
        return max(1, int(round(h * 60)))

    # 3) Somente minutos: "30m", "45 min"
    m = re.match(r"^\s*(\d+)\s*(m|min|mins|minutos?)\s*$", s)
    if m:
        return max(1, int(m.group(1)))

    # 4) Número puro => minutos
    if re.match(r"^\d+$", s):
        return max(1, int(s))

    # 5) "1 hora e 30 min"
    # Tenta extrair horas e minutos separadamente
    h = re.search(r"(\d+)\s*h(oras?)?", s)
    m = re.search(r"(\d+)\s*m(in(utos)?)?", s)
    if h or m:
        horas = int(h.group(1)) if h else 0
        mins = int(m.group(1)) if m else 0
        return max(1, horas * 60 + mins)

    # fallback
    return 30


def _read_table(file_storage, filename: str):
    """Lê CSV/XLSX com tolerância a encoding e separador; retorna DataFrame."""
    name = (filename or "").lower()

    # CSV
    if name.endswith(".csv"):
        # tenta UTF-8 -> Latin-1; separador vírgula -> ponto-e-vírgula
        for enc in ("utf-8", "latin-1"):
            try:
                file_storage.stream.seek(0)
                try:
                    return pd.read_csv(file_storage, encoding=enc)
                except Exception:
                    file_storage.stream.seek(0)
                    return pd.read_csv(file_storage, encoding=enc, sep=";")
            except Exception:
                continue
        raise ValueError("Falha ao ler CSV (enc/separador).")

    # XLSX (ou outros Excel)
    file_storage.stream.seek(0)
    try:
        return pd.read_excel(file_storage)
    except Exception as e:
        raise ValueError(f"Falha ao ler planilha: {e}")


# ---------------------------- Rota principal ----------------------------

@importar_bp.route('/api/importar-precos', methods=['POST'])
def importar_precos():
    uid = (request.form.get('uid') or 'demo').strip()

    arquivo = request.files.get('arquivo')
    if not arquivo:
        return ("Arquivo CSV/XLSX é obrigatório.", 400)

    content_type = (arquivo.content_type or "").lower()
    # Não bloqueamos por MIME (muitos navegadores mandam genérico), mas logamos:
    if content_type not in _ALLOWED_MIMES and not content_type.startswith("application/") and not content_type.startswith("text/"):
        # Apenas aviso leve – seguimos adiante
        pass

    # Limite opcional de linhas (pra evitar uploads gigantes em teste)
    try:
        limit = int(request.form.get("limit") or 0)
    except Exception:
        limit = 0

    # Lê a tabela
    try:
        df = _read_table(arquivo, arquivo.filename or "")
    except Exception as e:
        return (f"Falha ao ler tabela: {e}", 400)

    if df is None or df.empty:
        return ("Tabela vazia ou ilegível.", 400)

    # Corta se limite for informado
    if limit and limit > 0:
        df = df.head(limit)

    # Infere colunas
    c_nome, c_preco, c_dur = _infer_columns(df.columns)
    if not c_nome or not c_preco:
        return ("Colunas mínimas não encontradas (nome + preco/preço/valor).", 400)

    # Normaliza colunas
    nomes = df[c_nome].astype(str).fillna("").str.strip()
    precos = df[c_preco].apply(_parse_price)

    if c_dur:
        duracoes = df[c_dur].apply(_parse_duration_to_minutes)
    else:
        duracoes = pd.Series([30] * len(df))

    df_norm = pd.DataFrame({
        "nome": nomes,
        "preco": precos,
        "duracaoPadraoMin": duracoes
    })

    # Remove linhas sem nome
    df_norm = df_norm[df_norm["nome"] != ""]
    if df_norm.empty:
        return ("Após normalização, não restaram itens válidos (nomes vazios).", 400)

    # Persiste
    try:
        total = dbsvc.salvar_tabela_precos(uid, df_norm.to_dict(orient="records"))
    except Exception as e:
        return (f"Erro ao salvar no Firestore: {e}", 500)

    # Retorna um resumo (primeiros 3 itens) para debug visual
    sample = df_norm.head(3).to_dict(orient="records")

    return jsonify({
        "status": "ok",
        "uid": uid,
        "itens": int(total),
        "cols_usadas": {
            "nome": c_nome,
            "preco": c_preco,
            "duracao": c_dur
        },
        "amostra": sample
    })
