"""
Minimal, dependency-free test harness.

We can't `pip install pytest` in every environment (and DealBench prides itself
on running on the stdlib alone), so this discovers and runs every `test_*`
function across the test modules and prints a pytest-style summary.

    python3 backend/run_tests.py
"""
from __future__ import annotations

import importlib
import os
import sys
import traceback
from contextlib import contextmanager

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)


@contextmanager
def assert_raises(exc_type):
    """pytest.raises replacement so test files need no third-party deps."""
    raised = False
    try:
        yield
    except exc_type:
        raised = True
    except Exception as e:  # wrong exception type
        raise AssertionError(f"expected {exc_type.__name__}, got {type(e).__name__}: {e}")
    if not raised:
        raise AssertionError(f"expected {exc_type.__name__} to be raised, none was")


TEST_MODULES = [
    "tests.test_engine",
    "tests.test_stopping_rules",
    "tests.test_validator",
    "tests.test_classifier",
    "tests.test_control",
    "tests.test_grader",
]


def run() -> int:
    passed = failed = 0
    failures: list[str] = []

    for mod_name in TEST_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as e:
            # A module may not exist yet during incremental development.
            if mod_name.split(".")[-1] in str(e):
                print(f"  (skipping {mod_name}: not present yet)")
                continue
            raise
        fns = [getattr(mod, n) for n in dir(mod)
               if n.startswith("test_") and callable(getattr(mod, n))]
        for fn in fns:
            label = f"{mod_name}::{fn.__name__}"
            try:
                fn()
                passed += 1
                print(f"  PASS  {label}")
            except Exception:
                failed += 1
                failures.append(label + "\n" + traceback.format_exc())
                print(f"  FAIL  {label}")

    print("\n" + "=" * 60)
    if failures:
        print("FAILURES:\n")
        for f in failures:
            print(f)
    print(f"{passed} passed, {failed} failed")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
