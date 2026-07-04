#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Seed do KB no Firestore Emulator.

Uso no Windows CMD:
  set FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
  py kb_seed_v1/seed_firestore_emulator.py --only all

Opções:
  --only segments
  --only subsegments
  --only archetypes
  --only all
"""

import argparse
import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import firestore

BASE_DIR = Path(__file__).resolve().parent

FILES = {
    "segments": ("kb_segments_v1", BASE_DIR / "03_kb_segments_v1.json"),
    "subsegments": ("kb_subsegments_v1", BASE_DIR / "04_kb_subsegments_v1.json"),
    "archetypes": ("kb_archetypes_v1", BASE_DIR / "05_kb_archetypes_v1.json"),
}


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def init_firestore_emulator():
    host = os.environ.get("FIRESTORE_EMULATOR_HOST", "").strip()
    if not host:
        raise RuntimeError(
            "FIRESTORE_EMULATOR_HOST não definido. Ex.: set FIRESTORE_EMULATOR_HOST=127.0.0.1:8080"
        )

    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": "mei-robo-prod"})

    return firestore.client()


def upsert_collection(db, collection_name: str, items: list):
    batch = db.batch()
    count = 0

    for item in items:
        doc_id = item.get("id")
        if not doc_id:
            raise ValueError(f"Item sem campo 'id' em {collection_name}: {item}")

        payload = dict(item)
        payload.pop("id", None)

        doc_ref = db.collection(collection_name).document(doc_id)
        batch.set(doc_ref, payload, merge=True)
        count += 1

        if count % 400 == 0:
            batch.commit()
            batch = db.batch()

    batch.commit()
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        default="all",
        choices=["segments", "subsegments", "archetypes", "all"],
        help="Coleção a implantar",
    )
    args = parser.parse_args()

    db = init_firestore_emulator()

    if args.only == "all":
        selected = ["segments", "subsegments", "archetypes"]
    else:
        selected = [args.only]

    total = 0
    for key in selected:
        collection_name, json_path = FILES[key]
        items = load_json(json_path)
        inserted = upsert_collection(db, collection_name, items)
        total += inserted
        print(f"[OK] {collection_name}: {inserted} documento(s) processado(s)")

    print(f"[DONE] Total processado no Emulator: {total}")


if __name__ == "__main__":
    main()