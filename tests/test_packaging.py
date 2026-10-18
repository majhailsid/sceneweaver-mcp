import json
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import tarfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_bundle_whitelist_and_checksums(self):
        spec = importlib.util.spec_from_file_location('release_package', ROOT / 'scripts/package_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'pyproject.toml').write_text('[project]\nversion="0.1.0"\n', encoding='utf-8')
            (root / 'dist').mkdir()
            for name in ('sceneweaver_mcp-0.1.0-py3-none-any.whl', 'sceneweaver_mcp-0.1.0.tar.gz'):
                (root / 'dist' / name).write_bytes(b'build output')
            for name in ('README.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md', 'SECURITY.md'):
                (root / name).write_text(name, encoding='utf-8')
            (root / '.env').write_text('PRIVATE_TOKEN=secret', encoding='utf-8')
            for folder in ('docs', 'examples'):
                (root / folder).mkdir()
                (root / folder / 'guide.txt').write_text('public documentation', encoding='utf-8')
            with patch.object(module.subprocess, 'run') as build:
                bundle = module.package(root)
                build.assert_called_once()
            with zipfile.ZipFile(bundle) as archive:
                self.assertNotIn('.env', archive.namelist())
                self.assertIn('examples/guide.txt', archive.namelist())
                self.assertIn('NOTICE', archive.namelist())
            for line in (root / 'dist/SHA256SUMS').read_text(encoding='utf-8').splitlines():
                digest, name = line.split('  ', 1)
                self.assertEqual(digest, hashlib.sha256((root / 'dist' / name).read_bytes()).hexdigest())

    def test_metadata_and_client_example(self):
        metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertEqual(metadata['project']['license'], 'Apache-2.0')
        self.assertEqual(metadata['project']['scripts']['sceneweaver-mcp'],
                         'sceneweaver_mcp.__main__:main')
        self.assertFalse(any('moviepy' in item.lower() for item in metadata['project']['dependencies']))
        config = json.loads((ROOT / 'examples/mcp.json').read_text(encoding='utf-8'))
        self.assertEqual(config['mcpServers']['sceneweaver']['args'], ['serve'])

    def test_built_wheel_has_code_not_private_state(self):
        wheels = sorted((ROOT / 'dist').glob('*.whl'))
        if not wheels:
            self.skipTest('Run scripts/package_release.py to inspect built artifacts')
        with zipfile.ZipFile(wheels[-1]) as archive:
            names = archive.namelist()
            self.assertIn('sceneweaver_mcp/__main__.py', names)
            self.assertIn('sceneweaver_mcp/clients.py', names)
            self.assertTrue(any(name.endswith('/licenses/LICENSE') for name in names))
            for name in names:
                self.assertFalse(any(part in name.split('/') for part in
                                     ('.venv', 'node_modules', 'models', 'cache', 'jobs', 'runtime', '.env', '__pycache__')))
                self.assertFalse(name.endswith(('.pyc','.pyo')))
            resources = ROOT / 'src/sceneweaver_mcp/resources'
            for folder in (resources, ROOT / 'src/sceneweaver_mcp/integrations'):
                for source in folder.rglob('*'):
                    if source.is_file() and not source.is_symlink() and '__pycache__' not in source.parts:
                        self.assertIn(source.relative_to(ROOT / 'src').as_posix(), names)

    def test_built_source_contains_install_and_build_material(self):
        sources = sorted((ROOT / 'dist').glob('*.tar.gz'))
        if not sources:
            self.skipTest('Run scripts/package_release.py to inspect built artifacts')
        with tarfile.open(sources[-1], 'r:gz') as archive:
            names = {name.split('/', 1)[1] for name in archive.getnames() if '/' in name}
        for required in ('MANIFEST.in', 'SECURITY.md', 'docs/integrations.md', 'docs/clients.md',
                         'examples/install-windows.cmd', 'examples/install-posix.sh',
                         'examples/run-windows.cmd', 'examples/run-posix.sh',
                         'scripts/package_release.py', '.github/workflows/check.yml'):
            self.assertIn(required, names)
        for name in names:
            self.assertFalse(any(part in name.split('/') for part in
                                 ('.venv', 'node_modules', 'models', 'cache', 'jobs', 'runtime', '.env')))


if __name__ == '__main__':
    unittest.main()
