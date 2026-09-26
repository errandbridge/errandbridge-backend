from __future__ import annotations
import sys
import os
import pathlib

# Ensure root repository directory is on sys.path so modules like main, database, models can be imported
root_dir = str(pathlib.Path(__file__).parent.parent.resolve())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    import crypt
except ImportError:
    import types
    sys.modules["crypt"] = types.ModuleType("crypt")

from main import app
app = app
