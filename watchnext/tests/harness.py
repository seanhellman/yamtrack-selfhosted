"""Shared runner for the test files in this directory.

Stdlib-only and imported by path, so each test file still runs on its own with
`python3 watchnext/tests/test_<name>.py` and no virtualenv — the property that
makes them worth having at all.
"""

passes = fails = 0


def check(label, cond, detail=""):
    """Record one assertion and print its result."""
    global passes, fails
    passes, fails = passes + bool(cond), fails + (not cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")


def guard(name, fn):
    """Run fn, turning anything it raises into a failure rather than letting it
    abort the run and hide every test after it."""
    try:
        fn()
    except Exception as exc:
        check(f"{name} raised", False, f"{type(exc).__name__}: {exc}")


def summary():
    """Print the footer and return the process exit code."""
    print(f"\n==== {passes} passed, {fails} failed ====")
    return 1 if fails else 0


def run(namespace):
    """Run every test_* callable in namespace, then report. Returns exit code."""
    for name, fn in sorted(namespace.items()):
        if name.startswith("test_") and callable(fn):
            guard(name, fn)
    return summary()
