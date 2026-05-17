"""Root conftest: ensure backend package root is on sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow bare imports like `import storage`, `from models.document import ...`
_backend_root = Path(__file__).parent
sys.path.insert(0, str(_backend_root))
