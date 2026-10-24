import os
from pathlib import Path

os.environ.setdefault("FASTEMBED_CACHE_PATH", str(Path("/workspace/.cache/fastembed")))
os.environ.setdefault("KEEL_SKIP_TRAFFIC", "1")
