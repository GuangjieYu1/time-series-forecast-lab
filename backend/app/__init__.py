from __future__ import annotations

import os

# Keep pandas from importing incompatible optional accelerators from the host env.
os.environ.setdefault("PANDAS_NO_IMPORT_NUMEXPR", "1")
os.environ.setdefault("PANDAS_NO_IMPORT_BOTTLENECK", "1")
