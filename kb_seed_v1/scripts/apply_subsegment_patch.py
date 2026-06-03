import argparse
import json
from pathlib import Path


def load_json(path: str) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def print_summary(data: dict, collection: str, doc_id: str, project: str) -> None:
    print("=== SUBSEGMENT PATCH DRY-RUN ===")
    print(f"Projeto: {project}")
    print(f"Coleção: {collection}")
    print(f"Documento: {doc_id}")
    print(f"Campos no patch: {len(data.keys())}")
    print("")
    print("Campos:")
    for key in sorted(data.keys()):
        value = data[key]
        if isinstance(value, list):
            print(f"- {key}: list[{len(value)}]")
        elif isinstance(value, dict):
            print(f"- {key}: map[{len(value)}]")
        else:
            print(f"- {key}: {type(value).__name__}")
    print("")
    print("Nenhuma gravação foi executada.")


def apply_patch(data: dict, collection: str, doc_id: str, project: str, credentials_path: str | None) -> None:
    import firebase_admin
    from firebase_admin import credentials, firestore

    if not firebase_admin._apps:
        if credentials_path:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred, {"projectId": project})
        else:
            firebase_admin.initialize_app(options={"projectId": project})

    db = firestore.client()
    ref = db.collection(collection).document(doc_id)
    ref.set(data, merge=True)

    print("=== SUBSEGMENT PATCH APLICADO ===")
    print(f"Projeto: {project}")
    print(f"Coleção: {collection}")
    print(f"Documento: {doc_id}")
    print("Modo: merge=True")
    print("Status: concluído")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aplica patch seguro de subsegmento no Firestore."
    )

    parser.add_argument("--file", required=True, help="Caminho do JSON de patch.")
    parser.add_argument("--project", default="mei-robo-prod", help="ID do projeto GCP.")
    parser.add_argument("--collection", default="kb_subsegments_v1", help="Coleção Firestore.")
    parser.add_argument("--doc", default="comercio_varejista__loja_oculos", help="Documento alvo.")
    parser.add_argument("--credentials", default=None, help="Opcional: caminho para service account JSON.")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Valida e mostra o que seria aplicado.")
    mode.add_argument("--apply", action="store_true", help="Aplica no Firestore com merge=True.")

    args = parser.parse_args()
    data = load_json(args.file)

    if args.dry_run:
        print_summary(data, args.collection, args.doc, args.project)
        return

    if args.apply:
        apply_patch(data, args.collection, args.doc, args.project, args.credentials)


if __name__ == "__main__":
    main()

