"""Consistent, uniquely named rollback copies for opt-in world extensions."""
import sqlite3
import uuid
from pathlib import Path


def rollback_backup(world, feature):
    """Call before any writes while the caller holds its transaction reservation."""
    backup = Path(world.path).with_name(Path(world.path).name + f".pre-{feature}-{uuid.uuid4().hex}.bak")
    source = sqlite3.connect(Path(world.path).resolve().as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        source.close()
        target.close()
    return str(backup.resolve())
