"""Managed application state; no tool may choose an arbitrary filesystem root."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from uuid import UUID, uuid4


def home() -> Path:
    configured = os.environ.get('SCENEWEAVER_HOME')
    if configured:
        root = Path(configured).expanduser().absolute()
    elif os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'SceneWeaver'
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'sceneweaver'
    root.mkdir(parents=True, exist_ok=True)
    return contained(root, root)


def contained(root: Path, path: Path) -> Path:
    root = Path(os.path.abspath(root))
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise ValueError('Path outside managed storage')
    for part in (path, *path.parents):
        if not part.is_relative_to(root):break
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked storage paths are not allowed')
    resolved=path.resolve()
    if not resolved.is_relative_to(root.resolve()):raise ValueError('Path outside managed storage')
    return resolved


def write_json(path: Path, value) -> None:
    safe = contained(home(), path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    temporary = safe.with_name(safe.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, safe)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path, default=None):
    safe = contained(home(), path)
    if not safe.exists():
        return default
    if safe.stat().st_size > 2*1024**2:
        raise ValueError('State document exceeds size limit')
    return json.loads(safe.read_text(encoding='utf-8'))


def identifier(value: str) -> str:
    try:
        valid = str(UUID(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError('Invalid identifier') from None
    if valid != value:
        raise ValueError('Invalid identifier')
    return valid
