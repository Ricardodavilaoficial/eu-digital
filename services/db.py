# services/db.py
# Cliente Firestore via Firebase Admin — inicialização robusta e helpers
# Compatível com:
#   from services.db import get_db
#   from services import db as dbsvc  (compat: dbsvc.db.document(...))

import os
import json
from datetime import datetime
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore as fa_firestore


# ------------------------
# Utilidades de timestamp
# ------------------------
def now_ts() -> str:
    """Retorna ISO8601 UTC com 'Z' no fim (string)."""
    return datetime.utcnow().isoformat() + "Z"


# -----------------------------------
# Inicialização do Firebase / Firestore
# -----------------------------------
_APP: Optional[firebase_admin.App] = None
_DB: Optional[fa_firestore.Client] = None


def _load_credentials_from_inline_json():
    """
    Tenta ler credenciais do ambiente (JSON inline), nesta ordem:
      1) FIREBASE_CREDENTIALS_JSON (preferido)
      2) FIREBASE_SERVICE_ACCOUNT_JSON (compat)
      3) GOOGLE_APPLICATION_CREDENTIALS_JSON (para SDKs GCP usando a mesma chave)
    Retorna (cred_obj, project_id_from_key) ou (None, None) se não houver.
    """
    raw = (
        os.getenv("FIREBASE_CREDENTIALS_JSON")
        or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        or ""
    ).strip()
    if not raw:
        return None, None
    try:
        key_dict = json.loads(raw)
        cred = credentials.Certificate(key_dict)
        return cred, key_dict.get("project_id")
    except Exception as e:
        print("[FIREBASE] ERRO ao ler JSON inline de credencial:", e)
        return None, None


def _load_credentials_from_file():
    """
    Fallback: tenta ler do caminho GOOGLE_APPLICATION_CREDENTIALS (arquivo .json no filesystem).
    Retorna (cred_obj, project_id_from_key) ou (None, None) se ausente/inválido.
    """
    path = (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
    if not path:
        return None, None
    if not os.path.exists(path):
        print(f"[FIREBASE] Arquivo não encontrado em GOOGLE_APPLICATION_CREDENTIALS: {path}")
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            key_dict = json.load(f)
        cred = credentials.Certificate(key_dict)
        return cred, key_dict.get("project_id")
    except Exception as e:
        print("[FIREBASE] ERRO ao ler GOOGLE_APPLICATION_CREDENTIALS:", e)
        return None, None


def _ensure_project_match(key_project_id: Optional[str], env_project_id: Optional[str]):
    """Garante que o project_id da chave bate com o do ENV."""
    if not env_project_id:
        raise RuntimeError("[FIREBASE] Variável FIREBASE_PROJECT_ID ausente.")
    if not key_project_id:
        raise RuntimeError("[FIREBASE] project_id ausente dentro da chave de serviço.")
    if key_project_id != env_project_id:
        raise RuntimeError(
            f"[FIREBASE] Project mismatch: key={key_project_id} env={env_project_id}"
        )


def _init_firebase_app() -> firebase_admin.App:
    """
    Inicializa o firebase_admin.App uma única vez, priorizando:
      1) JSON inline (FIREBASE_CREDENTIALS_JSON | FIREBASE_SERVICE_ACCOUNT_JSON | GOOGLE_APPLICATION_CREDENTIALS_JSON)
      2) Caminho de arquivo (GOOGLE_APPLICATION_CREDENTIALS)
    Bloqueia ADC implícito para evitar vazar para projeto errado.
    """
    global _APP

    if _APP is not None:
        return _APP

    # Se outro ponto do código já inicializou, reaproveita
    try:
        _APP = firebase_admin.get_app()
        return _APP
    except ValueError:
        pass  # ainda não inicializado

    env_project_id = (os.getenv("FIREBASE_PROJECT_ID") or "").strip()
    if not env_project_id:
        raise RuntimeError("[FIREBASE] FIREBASE_PROJECT_ID não definido.")

    # 1) JSON inline (preferido)
    cred, key_pid = _load_credentials_from_inline_json()
    if cred:
        _ensure_project_match(key_pid, env_project_id)
        print("[FIREBASE] Usando credencial inline (env JSON).")
        _APP = firebase_admin.initialize_app(cred, {"projectId": env_project_id})
        return _APP

    # 2) Caminho de arquivo (fallback)
    cred, key_pid = _load_credentials_from_file()
    if cred:
        _ensure_project_match(key_pid, env_project_id)
        print("[FIREBASE] Usando credencial via arquivo (GOOGLE_APPLICATION_CREDENTIALS).")
        _APP = firebase_admin.initialize_app(cred, {"projectId": env_project_id})
        return _APP

    # 3) Bloqueia ADC
    raise RuntimeError(
        "[FIREBASE] Nenhuma credencial encontrada. Defina FIREBASE_CREDENTIALS_JSON "
        "(ou FIREBASE_SERVICE_ACCOUNT_JSON/GOOGLE_APPLICATION_CREDENTIALS_JSON) "
        "ou GOOGLE_APPLICATION_CREDENTIALS (arquivo)."
    )


def get_db() -> fa_firestore.Client:
    """Retorna um client do Firestore (cacheado)."""
    global _DB
    if _DB is not None:
        return _DB
    _init_firebase_app()
    _DB = fa_firestore.client()
    return _DB


def reset_db_for_tests():
    """Reseta singletons (útil em testes)."""
    global _APP, _DB
    try:
        if _APP is not None:
            firebase_admin.delete_app(_APP)
    except Exception:
        pass
    _APP = None
    _DB = None


# -------------------------------
# Compat: exporta 'db' como lazy
# -------------------------------
class _LazyFirestore:
    """
    Wrapper que inicializa o client só quando for usado.
    Permite chamadas como: db.document(...), db.collection(...), etc.
    """
    _client: Optional[fa_firestore.Client] = None

    def _ensure(self):
        if self._client is None:
            self._client = get_db()

    def __getattr__(self, name):
        self._ensure()
        return getattr(self._client, name)

    def __repr__(self):
        return "<LazyFirestore: pending>" if self._client is None else repr(self._client)


db = _LazyFirestore()  # compat: from services import db as dbsvc


# ------------------------
# Helpers genéricos (CRUD)
# ------------------------
def get_doc(path: str):
    """Lê um documento por caminho 'colecao/doc[/subcolecao/doc]'."""
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

        # Commit a cada ~400 (limite 500; 400 dá folga)
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    # Commit final
    batch.commit()
    return count
