import sys
from pathlib import Path


# Ensure the project root (/app) is importable when tests are executed.
# Depending on how pytest is invoked, the working directory can make absolute
# imports like `import ml_client` fail.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
