from __future__ import annotations

import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).joinpath(*parts)

    if "__compiled__" in globals():
        executable_directory = Path(sys.executable).resolve().parent
        candidates = (
            executable_directory.joinpath(*parts),
            executable_directory.parent.joinpath("Resources", *parts),
        )
        return next((path for path in candidates if path.exists()), candidates[0])

    return Path(__file__).resolve().parents[2].joinpath(*parts)
