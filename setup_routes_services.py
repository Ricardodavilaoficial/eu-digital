
# setup_routes_services.py — cria módulos e patcha o app.py de forma segura
import os, io, re, time, shutil, sys, textwrap

CNPJ_BP_CODE = r"""from flask import Blueprint, jsonify
from services.cnpj_client import fetch_cnpj_info

cnpj_bp = Blueprint("cnpj_publica", __name__, url_prefix="/api")

@cnpj_bp.route("/cnpj/<cnpj>", methods=["GET"])
def get_cnpj(cnpj):
    info = fetch_cnpj_info(cnpj)
    if not info:
        return jsonify({"ok": False, "error": "not_found_or_invalid"}), 404
    return jsonify({"ok": True, "data": info}), 200
"""

CNPJ_CLIENT_CODE = r"""import re
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
"""

VOZ_BP_CODE = r"""# Placeholder seguro da Voz V2 (desligado por flag por padrão)
from flask import Blueprint, jsonify

voz_upload_bp = Blueprint("voz_upload_v2", __name__, url_prefix="/api")

@voz_upload_bp.route("/configuracao", methods=["POST"])
def upload_voz_config():
    # Ainda não ativado: quando VOZ_V2_ENABLED=true, ideal é apontar para a nova lógica
    # Mantido placeholder para não surpreender; por padrão, flag fica OFF.
    return jsonify({"ok": False, "error": "voz_v2_disabled"}), 501
"""

VOICE_VALIDATION_CODE = r"""# services/voice_validation.py — validações de áudio (placeholder seguro)
def validate_audio(file_path, min_seconds=60, max_mb=50, min_khz=16, max_khz=48):
    \"\"\"Devolve dict com {ok, errors[]} sem levantar exceções.\"\"\"
    return {"ok": True, "errors": []}
"""

STORAGE_GCS_CODE = r"""# services/storage_gcs.py — operações com Storage (placeholder seguro)
def generate_signed_url(path, expires_seconds=3600, method="GET"):
    return None
"""

VOICE_METADATA_CODE = r"""# services/voice_metadata.py — gravação de metadados (placeholder seguro)
def save_voice_metadata(uid, meta: dict):
    return True
"""

PATCH_BLOCKS = [
    # CNPJ blueprint guarded
    {
        "import": "from routes.cnpj_publica import cnpj_bp",
        "register": (
            "try:\n"
            "    from routes.cnpj_publica import cnpj_bp\n"
            "    if os.getenv('CNPJ_BP_ENABLED') == 'true':\n"
            "        app.register_blueprint(cnpj_bp)\n"
            "except Exception as e:\n"
            "    logging.warning('CNPJ_BP disabled or import failed: %s', e)\n"
        ),
    },
    # VOZ blueprint guarded
    {
        "import": "from routes.voz_upload_bp import voz_upload_bp",
        "register": (
            "try:\n"
            "    from routes.voz_upload_bp import voz_upload_bp\n"
            "    if os.getenv('VOZ_V2_ENABLED') == 'true':\n"
            "        app.register_blueprint(voz_upload_bp)\n"
            "except Exception as e:\n"
            "    logging.warning('VOZ_V2 disabled or import failed: %s', e)\n"
        ),
    },
]

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def write_if_missing(path, content):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        return True
    return False

def backup(path):
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = f"{path}.bak-{ts}"
    shutil.copy2(path, dst)
    return dst

def patch_app_py(app_path):
    with open(app_path, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    original = src
    backed = backup(app_path)

    # Inserir imports se faltarem (no topo, após últimos imports)
    lines = src.splitlines()
    last_import_idx = -1
    for i, line in enumerate(lines[:400]):
        if line.strip().startswith(("import ", "from ")):
            last_import_idx = i

    for blk in PATCH_BLOCKS:
        if blk["import"] not in src:
            insert_idx = max(0, last_import_idx + 1)
            lines.insert(insert_idx, blk["import"])
            last_import_idx = insert_idx

    src = "\n".join(lines)

    # Inserir registros antes do if __name__ == "__main__"
    main_anchor = re.search(r"\nif\s+__name__\s*==\s*['\\\"]__main__['\\\"]\s*:", src)
    register_text = "\n\n# --- Modular Blueprints (guarded by ENV flags) ---\n" + \
        "\n".join(blk["register"] for blk in PATCH_BLOCKS) + "\n"

    if register_text.strip() not in src:
        if main_anchor:
            idx = main_anchor.start()
            src = src[:idx] + register_text + src[idx:]
        else:
            src = src.rstrip() + register_text

    if src != original:
        with open(app_path, "w", encoding="utf-8") as f:
            f.write(src)
        print("PATCH OK — app.py atualizado. Backup:", backed)
    else:
        print("Nada a patchar. Backup criado:", backed)

def main():
    base = os.getcwd()
    # Criar pastas
    ensure_dir(os.path.join(base, "routes"))
    ensure_dir(os.path.join(base, "services"))

    # Criar arquivos (somente se não existirem)
    wrote = []
    if write_if_missing(os.path.join(base, "routes", "cnpj_publica.py"), CNPJ_BP_CODE):
        wrote.append("routes/cnpj_publica.py")
    if write_if_missing(os.path.join(base, "services", "cnpj_client.py"), CNPJ_CLIENT_CODE):
        wrote.append("services/cnpj_client.py")

    if write_if_missing(os.path.join(base, "routes", "voz_upload_bp.py"), VOZ_BP_CODE):
        wrote.append("routes/voz_upload_bp.py")
    if write_if_missing(os.path.join(base, "services", "voice_validation.py"), VOICE_VALIDATION_CODE):
        wrote.append("services/voice_validation.py")
    if write_if_missing(os.path.join(base, "services", "storage_gcs.py"), STORAGE_GCS_CODE):
        wrote.append("services/storage_gcs.py")
    if write_if_missing(os.path.join(base, "services", "voice_metadata.py"), VOICE_METADATA_CODE):
        wrote.append("services/voice_metadata.py")

    print("Arquivos criados:", ", ".join(wrote) if wrote else "(nenhum — já existiam)")

    # Patch app.py (na pasta atual)
    app_path = os.path.join(base, "app.py")
    if not os.path.isfile(app_path):
        print("ERRO: app.py não encontrado nesta pasta:", base)
        sys.exit(2)

    patch_app_py(app_path)
    print("Concluído com sucesso. Flags padrão: OFF (nada muda até você habilitar).")

if __name__ == "__main__":
    main()
