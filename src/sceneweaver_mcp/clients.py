"""Installer-only client discovery and explicitly requested local registration."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import tomllib
from uuid import uuid4

MAX_CONFIG_BYTES = 1024 * 1024


def discover() -> list[dict]:
    """Check known config locations only; never scan processes, disks, or credentials."""
    user = Path.home()
    locations = [
        ('codex', 'Codex', Path(os.environ.get('CODEX_HOME') or user / '.codex') / 'config.toml'),
        ('cursor', 'Cursor', user / '.cursor' / 'mcp.json'),
    ]
    if sys.platform == 'win32':
        locations.append(('claude-desktop', 'Claude Desktop',
                          Path(os.environ.get('APPDATA') or user / 'AppData/Roaming') /
                          'Claude' / 'claude_desktop_config.json'))
    elif sys.platform == 'darwin':
        locations.append(('claude-desktop', 'Claude Desktop',
                          user / 'Library/Application Support/Claude/claude_desktop_config.json'))
    return [{'id': key, 'name': name, 'config_path': str(path.expanduser().absolute()),
             'detected': path.expanduser().parent.is_dir()} for key, name, path in locations]


def _safe(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked client configuration paths require manual setup')


def _read(path: Path) -> bytes | None:
    _safe(path)
    if not path.exists():
        return None
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Client configuration must be a regular file')
    with path.open('rb') as stream:
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError('Client configuration exceeds 1 MiB; use manual setup')
    return data


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate configuration keys require manual setup')
        result[key] = value
    return result


def _commit(path: Path, original: bytes | None, updated: bytes) -> str | None:
    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe(path)
    backup = path.with_name(path.name + '.sceneweaver-backup-' + uuid4().hex) if original is not None else None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.sceneweaver-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(path) != original:
            raise ValueError('Client configuration changed; close the client and try again')
        if original is None:
            # Both operations refuse to overwrite a concurrently created config.
            if os.name == 'nt':os.rename(temporary, path)
            else:os.link(temporary, path)
        elif os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            replace = kernel.ReplaceFileW
            replace.argtypes = [wintypes.LPCWSTR] * 3 + [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
            replace.restype = wintypes.BOOL
            # ReplaceFile preserves the original ACL and creates its backup on the same volume.
            if not replace(str(path), str(temporary), str(backup), 0, None, None):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                stream.write(original)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
            if _read(path) != original:
                raise ValueError('Client configuration changed; close the client and try again')
            os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(backup) if backup else None


def connect(client: str, dry_run: bool = False) -> dict:
    selected = next((item for item in discover() if item['id'] == client), None)
    if selected is None:
        raise ValueError('Unsupported client on this platform')
    path = Path(selected['config_path'])
    original = _read(path)
    text = (original or b'').decode('utf-8-sig')
    entry = {'command': str(Path(sys.executable).absolute()),
             'args': ['-m', 'sceneweaver_mcp', 'serve']}
    try:
        if client == 'codex':
            config = tomllib.loads(text)
            servers = config.get('mcp_servers', {})
        else:
            config = json.loads(text, object_pairs_hook=_unique) if original is not None else {}
            if not isinstance(config, dict):
                raise ValueError('Client configuration must be an object')
            servers = config.get('mcpServers', {})
        if not isinstance(servers, dict):
            raise ValueError('The client server collection must be an object')
        if 'sceneweaver' in servers:
            if servers['sceneweaver'] == entry:
                return {'client': client, 'status': 'already_connected', 'config_path': str(path)}
            raise ValueError('A different SceneWeaver entry already exists; edit it in the client before reconnecting')
        if client == 'codex':
            updated = text.rstrip() + '\n\n[mcp_servers.sceneweaver]\n'
            updated += 'command = ' + json.dumps(entry['command'], ensure_ascii=False) + '\n'
            updated += 'args = ' + json.dumps(entry['args']) + '\n'
            tomllib.loads(updated)
        else:
            config.setdefault('mcpServers', {})['sceneweaver'] = entry
            updated = json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    except (tomllib.TOMLDecodeError, json.JSONDecodeError):
        raise ValueError('Invalid or unsupported client configuration; use manual setup') from None
    result = {'client': client, 'status': 'preview' if dry_run else 'connected',
              'config_path': str(path), 'entry': entry}
    if len(updated.encode('utf-8')) > MAX_CONFIG_BYTES:
        raise ValueError('Updated configuration would exceed 1 MiB; use manual setup')
    if not dry_run:
        result['backup_path'] = _commit(path, original, updated.encode('utf-8'))
        result['next_step'] = 'Restart the selected client and approve SceneWeaver there. Keep this Python environment installed.'
    return result


def wizard() -> dict:
    detected = [item for item in discover() if item['detected']]
    print('SceneWeaver client setup: known configuration folders only; no settings changed yet.')
    if not detected:
        return {'status': 'skipped', 'reason': 'No supported client configuration folder found. Use clients or connect --client CLIENT.'}
    for number, item in enumerate(detected, 1):
        print(f"{number}. {item['name']}: {item['config_path']}")
    print('Close the selected client first. Choosing a number adds only SceneWeaver and backs up existing settings.')
    if not sys.stdin.isatty():
        return {'status': 'skipped', 'reason': 'Non-interactive install. Run connect --client CLIENT explicitly to opt in.'}
    try:
        choice = input('Connect to which client? Enter a number, or press Enter to skip: ').strip()
    except EOFError:
        choice = ''
    if not choice:
        return {'status': 'skipped'}
    if not choice.isascii() or not choice.isdigit() or not 1 <= int(choice) <= len(detected):
        raise ValueError('Invalid client choice; no configuration was changed')
    return connect(detected[int(choice) - 1]['id'])
