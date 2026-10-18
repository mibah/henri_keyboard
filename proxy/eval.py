"""Testet den Prompt gegen die Fälle in cases.json.

  python3 eval.py [Modell ...]     z. B. python3 eval.py qwen3:4b llama3:8b

Spricht direkt mit LLM_BASE_URL (default Ollama), nutzt dieselbe correct()-Funktion wie der Proxy.
"""
import json
import os
import sys
import re
import time

import server

cases = json.load(open(os.path.join(os.path.dirname(__file__), "cases.json"), encoding="utf-8"))
models = sys.argv[1:] or [server.MODEL]

for model in models:
    server.MODEL = model
    print(f"\n=== {model} ===")
    exact, loose, total_t = 0, 0, 0.0
    norm = lambda t: re.sub(r"[^\w]", "", t.lower())
    for c in cases:
        t = time.time()
        got = server.correct(c["in"])
        dt = time.time() - t
        total_t += dt
        ok = got == c["out"]
        exact += ok
        loose += norm(got) == norm(c["out"])
        print(f"{'OK ' if ok else 'DIF'} {dt:4.1f}s  {c['in']}\n         -> {got}")
        if not ok:
            print(f"         soll {c['out']}")
    print(f"\n{exact}/{len(cases)} exakt, {loose}/{len(cases)} ohne Satzzeichen/Groß-Klein, Ø {total_t/len(cases):.1f}s pro Anfrage")
