import os
import sys


def pytest_configure():
    # Ensure `src/` is importable as top-level for `common.*` imports
    root = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    src_path = os.path.join(root, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

