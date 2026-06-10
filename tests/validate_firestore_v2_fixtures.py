import json
import os
import sys

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__),
    "fixtures",
    "firestore_v2"
)

REQUIRED_FIELDS = {
    "commercial_runtime",
    "operational_runtime",
    "medical_runtime",
    "behavior_components",
    "snapshot_priority",
}


def validate_fixture(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    errors = []

    if "subsegment_id" not in data:
        errors.append("subsegment_id ausente")

    if "required_v2_fields" not in data:
        errors.append("required_v2_fields ausente")
        return errors

    fields = set(data["required_v2_fields"])

    missing = REQUIRED_FIELDS - fields

    if missing:
        errors.append(
            f"campos obrigatórios ausentes: {sorted(missing)}"
        )

    return errors


def main():
    print("")
    print("====================================")
    print("VALIDADOR FIRESTORE V2")
    print("====================================")
    print("")

    failures = 0

    files = sorted(
        f for f in os.listdir(FIXTURE_DIR)
        if f.endswith(".json")
    )

    if not files:
        print("ERRO: nenhum fixture encontrado.")
        sys.exit(1)

    for filename in files:
        path = os.path.join(FIXTURE_DIR, filename)

        try:
            errors = validate_fixture(path)

            if errors:
                failures += 1
                print(f"[ERRO] {filename}")

                for err in errors:
                    print(f"       - {err}")

            else:
                print(f"[OK]   {filename}")

        except Exception as exc:
            failures += 1
            print(f"[ERRO] {filename}")
            print(f"       - {exc}")

    print("")

    if failures:
        print(f"VALIDAÇÃO FINAL: {failures} erro(s)")
        sys.exit(1)

    print("VALIDAÇÃO FINAL: SUCESSO")
    sys.exit(0)


if __name__ == "__main__":
    main()