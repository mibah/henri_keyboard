"""Startet die Testreihe.

    python3 tests/run_tests.py                  # alle ohne Ollama (Bestand + Neu)
    python3 tests/run_tests.py bestand          # nur das, was schon vor dem Anbieter-Feature funktioniert hat
    python3 tests/run_tests.py neu              # nur das Anbieter-Feature
    python3 tests/run_tests.py --integration    # zusätzlich der komplette Ablauf mit echtem Ollama (gemma3:4b)
    python3 tests/run_tests.py --build          # zusätzlich die Android-App bauen (braucht JDK und Android-SDK)

Gegen einen anderen Projektstand: HENRI_ROOT=/pfad/zum/ordner python3 tests/run_tests.py bestand
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main(argv):
    which = next((a for a in argv if a in ("bestand", "neu", "alle")), "alle")
    if "--integration" in argv:
        os.environ["HENRI_INTEGRATION"] = "1"
    patterns = {"bestand": ["test_bestand_*.py"], "neu": ["test_neu_*.py"], "alle": ["test_bestand_*.py", "test_neu_*.py"]}[which]
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(HERE, pattern=pattern, top_level_dir=HERE))
    result = unittest.TextTestRunner(verbosity=2 if "-v" in argv else 1).run(suite)
    ok = result.wasSuccessful()
    if "--build" in argv:
        import helpers
        print("\nAndroid-App bauen …")
        ok = subprocess.call(["./gradlew", "assembleDebug", "--console=plain"], cwd=os.path.join(helpers.ROOT, "keyboard")) == 0 and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
