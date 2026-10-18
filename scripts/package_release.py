"""Build a small installable release; no user state or downloaded assets."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tomllib
import zipfile


def package(root: Path) -> Path:
    version = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    subprocess.run([sys.executable, '-m', 'build', str(root)], check=True, cwd=root)
    dist = root / 'dist'
    artifacts = [dist / f'sceneweaver_mcp-{version}-py3-none-any.whl',
                 dist / f'sceneweaver_mcp-{version}.tar.gz']
    for artifact in artifacts:
        if not artifact.is_file():
            raise RuntimeError(f'Build did not produce {artifact.name}')
    bundle = dist / f'sceneweaver-mcp-{version}-local.zip'
    with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for source in artifacts + [root / name for name in
                                  ('README.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md')]:
            archive.write(source, source.name)
        for folder in ('docs', 'examples'):
            for source in sorted((root / folder).rglob('*')):
                if source.is_file() and not source.is_symlink() and '__pycache__' not in source.parts:
                    archive.write(source, source.relative_to(root).as_posix())
    checksums = []
    for artifact in artifacts + [bundle]:
        with artifact.open('rb') as stream:
            checksums.append(f'{hashlib.file_digest(stream, "sha256").hexdigest()}  {artifact.name}\n')
    (dist / 'SHA256SUMS').write_text(''.join(checksums), encoding='utf-8')
    return bundle


if __name__ == '__main__':
    print(package(Path(__file__).resolve().parents[1]))

