"""Imports the plugin as a package, the way Hermes does (its folder name has a hyphen)."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    if "grounded_web" in sys.modules:
        return sys.modules["grounded_web"]
    spec = importlib.util.spec_from_file_location("grounded_web", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["grounded_web"] = module
    spec.loader.exec_module(module)
    return module
