from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / "tmp_test_runtime"


@contextmanager
def runtime_dir(prefix: str):
    """Yield a writable test directory under the repository runtime root."""
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_ROOT / f"{prefix}-{uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
