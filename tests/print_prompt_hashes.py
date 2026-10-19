"""Gibt die Prüfsummen der Prompts aus, die test_bestand_prompts.py eingefroren hat.

Nur ausführen, wenn ein Prompt bewusst geändert wurde, und die Werte dann in den Test übernehmen:
    python3 tests/print_prompt_hashes.py
"""
import hashlib
import json

import helpers  # noqa: F401  (richtet den Importpfad ein)
import server


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def file_digest(name):
    with open(helpers.PROXY + "/" + name, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


if __name__ == "__main__":
    print("FILES = {")
    for name in ("prompt.txt", "prompt_reword.txt", "prompt_passage.txt"):
        print(f'    "{name}": "{file_digest(name)}",')
    print("}")
    print("SHOTS = {")
    for name in ("SHOTS", "REWORD_SHOTS", "PASSAGE_SHOTS"):
        print(f'    "{name}": "{digest(getattr(server, name))}",')
    print("}")
