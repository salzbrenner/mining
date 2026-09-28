"""On-demand .apkg backups of the Mining deck, per user request -- a full,
self-contained Anki export (notes, media, and scheduling/review history)
re-importable via Anki's own File > Import if something goes wrong. Not
automatic; triggered manually from the web UI.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path

from app import anki
from app.config import BACKUPS_DIR, SOURCE_DECK


@dataclass
class BackupInfo:
    filename: str
    size_bytes: int
    created_at: datetime.datetime


def list_backups() -> list[BackupInfo]:
    if not BACKUPS_DIR.exists():
        return []
    backups = []
    for p in sorted(BACKUPS_DIR.glob("*.apkg"), reverse=True):
        stat = p.stat()
        backups.append(
            BackupInfo(
                filename=p.name,
                size_bytes=stat.st_size,
                created_at=datetime.datetime.fromtimestamp(stat.st_mtime),
            )
        )
    return backups


async def backup_mining() -> BackupInfo:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"Mining_{timestamp}.apkg"
    path: Path = BACKUPS_DIR / filename
    await anki.export_package(SOURCE_DECK, str(path), include_sched=True)
    stat = path.stat()
    return BackupInfo(
        filename=filename,
        size_bytes=stat.st_size,
        created_at=datetime.datetime.fromtimestamp(stat.st_mtime),
    )
