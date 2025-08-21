# services/db.py
# Cliente Firestore via Firebase Admin — inicialização robusta e helpers
# Compatível com: from services import db as dbsvc

import os
import json
from datetime import datetime

import firebase_admin
from firebase_admin import credentials, firestore as fa_firestore


# ------------------------
# Utilidades de timestamp
# ------------------------
def now_ts() -> str:
    """Retorna ISO8601 UTC com 'Z' no fim (string)."""
    return datetime.utcnow().isoformat() + "Z"


# ------------------------
# Inicialização do Firebase
# ------------------------
def _init_firebase():
    """
    Ordem de prioridade para credenciais (evita var antiga quebrando):
    1) FIREBASE_SERVICE_ACCOUNT_JSON (JSON colado na variável)
    2) GOOGLE_APPLICATION_CREDENTIALS (caminho p/ arquivo .json)
    3) Application Default Credentials (ADC)
    """
    if firebase_admin._apps:
        return firebase_admin.get_app()

    sa_json = (os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON") or "").strip()
    sa_path = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()

    cred = None

    # 1) JSON inline em env var
    if sa_json:
        try:
            cred = credentials.Certificate(json.loads(sa_json))
            print("[FIREBASE] Using FIREBASE_SERVICE_ACCOUNT_JSON")
        except Exception as e:
            print("[FIREBASE] Invalid FIREBASE_SERVICE_ACCOUNT_JSON:", e)

    # 2) Caminho de arquivo
    if cred is None and sa_path:
        if os.path.exists(sa_path):
            cred = credentials.Certificate(sa_path)
            print(f"[FIREBASE] Using GOOGLE_APPLICATION_CREDENTIALS file: {sa_path}")
        else:
            print(f"[FIREBASE] File not found at GOOGLE_APPLICATION_CREDENTIALS: {sa_path}")

    # 3) ADC (quando nem JSON nem path)
    if cred:
        return firebase_admin.initialize_app(cred)
    else:
        print("[FIREBASE] Using Application Default Credentials")
        return firebase_admin.initialize_app()


# Inicializa app/admin e client Firestore (global)
_init_firebase()
db = fa_firestore.client()


# ------------------------
# Helpers genéricos (CRUD)
# ------------------------
def get_doc(path: str):
    """Lê um documento por caminho 'colecao/doc/subcolecao/doc'."""
    snap = db.document(path).get()
    return snap.to_dict() if snap.exists else None


def set_doc(path: str, data: dict, merge: bool = True):
    """Cria/atualiza documento com merge por padrão."""
    if data is None:
        data = {}
    data.setdefault("updatedAt", now_ts())
    db.document(path).set(data, merge=merge)


def update_doc(path: str, data: dict):
    """Alias para set_doc com merge=True."""
    set_doc(path, data, merge=True)


def add_subdoc(col_path: str, data: dict) -> str:
    """
    Adiciona documento com ID aleatório em uma coleção (ex.: 'profissionais/{uid}/precos').
    Retorna o ID criado.
    """
    if data is None:
        data = {}
    ts = now_ts()
    data.setdefault("createdAt", ts)
    data.setdefault("updatedAt", ts)
    ref = db.collection(col_path).document()
    ref.set(data)
    return ref.id


# ---------------------------------------
# Funções específicas usadas pelas rotas
# ---------------------------------------
def salvar_config_profissional(uid: str, doc: dict):
    """
    Salva (com merge) os dados de configuração em 'profissionais/{uid}'.
    Não sobrescreve campos já existentes indevidamente.
    """
    if doc is None:
        doc = {}
    doc.setdefault("updatedAt", now_ts())
    path = f"profissionais/{uid}"
    db.document(path).set(doc, merge=True)


def salvar_tabela_precos(uid: str, itens: list) -> int:
    """
    Salva itens de preços em 'profissionais/{uid}/precos' usando batch.
    Campos mínimos esperados por item: nome, preco, duracaoPadraoMin.
    Retorna a quantidade persistida.
    """
    if not itens:
        return 0

    col = db.collection("profissionais").document(uid).collection("precos")
    batch = db.batch()
    count = 0

    for item in itens:
        # normaliza e acrescenta timestamps
        if not isinstance(item, dict):
            item = dict(item)
        ts = now_ts()
        item.setdefault("createdAt", ts)
        item["updatedAt"] = ts

        ref = col.document()  # ID aleatório
        batch.set(ref, item)
        count += 1

        # Commit a cada 400 (limite do Firestore é 500 por batch; 400 dá folga)
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    # Commit final
    batch.commit()
    return count
