import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from sceneweaver_mcp import clients
from sceneweaver_mcp.__main__ import main


class ClientSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.target = self.root / 'client settings' / 'mcp.json'
        self.locations = patch.object(clients, 'discover', return_value=[
            {'id': 'cursor', 'name': 'Cursor', 'config_path': str(self.target), 'detected': True},
            {'id': 'codex', 'name': 'Codex', 'config_path': str(self.target.with_suffix('.toml')), 'detected': True},
        ])
        self.locations.start()

    def tearDown(self):
        self.locations.stop()
        self.temp.cleanup()

    def write(self, data):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(data)

    def test_json_preserves_settings_backs_up_and_is_idempotent(self):
        original = b'{"theme":"dark","mcpServers":{"other":{"env":{"KEY":"private-sentinel"}}}}'
        self.write(original)
        result = clients.connect('cursor')
        self.assertEqual(Path(result['backup_path']).read_bytes(), original)
        config = json.loads(self.target.read_text())
        self.assertEqual(config['theme'], 'dark')
        self.assertEqual(config['mcpServers']['other']['env']['KEY'], 'private-sentinel')
        self.assertEqual(config['mcpServers']['sceneweaver']['args'], ['-m', 'sceneweaver_mcp', 'serve'])
        self.assertNotIn('private-sentinel', json.dumps(result))
        self.assertEqual(clients.connect('cursor')['status'], 'already_connected')
        self.assertEqual(len(list(self.target.parent.glob('*.sceneweaver-backup-*'))), 1)

    def test_toml_preserves_comments_and_existing_tables(self):
        target = self.target.with_suffix('.toml')
        target.parent.mkdir(parents=True)
        original = b'# keep my preferences\nmodel = "local"\n[mcp_servers.other]\ncommand = "other"\n'
        target.write_bytes(original)
        result = clients.connect('codex')
        content = target.read_text()
        self.assertTrue(content.startswith(original.decode().rstrip()))
        config = tomllib.loads(content)
        self.assertEqual(config['mcp_servers']['other']['command'], 'other')
        self.assertEqual(config['mcp_servers']['sceneweaver']['command'], str(Path(sys.executable).absolute()))
        self.assertEqual(Path(result['backup_path']).read_bytes(), original)
        self.assertEqual(clients.connect('codex')['status'], 'already_connected')

    def test_dry_run_creates_no_directories(self):
        result = clients.connect('cursor', dry_run=True)
        self.assertEqual(result['status'], 'preview')
        self.assertFalse(self.target.parent.exists())

    def test_new_configuration_is_complete_and_private(self):
        result = clients.connect('cursor')
        self.assertIsNone(result['backup_path'])
        self.assertIn('sceneweaver', json.loads(self.target.read_text())['mcpServers'])
        if os.name != 'nt':
            self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_conflicting_json_is_never_overwritten(self):
        for data in (b'{broken', b'{"mcpServers":[]}', b'[]', b'{"a":1,"a":2}',
                     b'{"mcpServers":{"sceneweaver":{"command":"custom"}}}', b'{"value":NaN}'):
            self.write(data)
            with self.assertRaises(ValueError):
                clients.connect('cursor')
            self.assertEqual(self.target.read_bytes(), data)
            self.assertFalse(list(self.target.parent.glob('*.sceneweaver-backup-*')))

    def test_unextendable_toml_is_never_overwritten(self):
        target = self.target.with_suffix('.toml')
        target.parent.mkdir(parents=True)
        for data in (b'mcp_servers = {}\n', b'[broken'):
            target.write_bytes(data)
            with self.assertRaises(ValueError):
                clients.connect('codex')
            self.assertEqual(target.read_bytes(), data)

    def test_oversized_config_is_refused(self):
        self.write(b' ' * (clients.MAX_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(ValueError, '1 MiB'):
            clients.connect('cursor')

    def test_linked_config_is_refused(self):
        self.target.parent.mkdir(parents=True)
        other = self.root / 'other.json'
        other.write_text('{}')
        try:
            self.target.symlink_to(other)
        except OSError:
            self.skipTest('Symlink creation is not available for this account')
        with self.assertRaisesRegex(ValueError, 'Linked'):
            clients.connect('cursor')
        self.assertEqual(other.read_text(), '{}')

    def test_changed_config_aborts_atomic_write(self):
        self.write(b'{}')
        with patch.object(clients, '_read', return_value=b'{"changed":true}'):
            with self.assertRaisesRegex(ValueError, 'changed'):
                clients._commit(self.target, b'{}', b'{"new":true}')
        self.assertEqual(self.target.read_bytes(), b'{}')
        self.assertEqual(list(self.target.parent.glob('.sceneweaver-*')), [])

    def test_wizard_never_writes_without_a_choice(self):
        with patch('sys.stdin.isatty', return_value=False), patch.object(clients, 'connect') as connect, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(clients.wizard()['status'], 'skipped')
            connect.assert_not_called()
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value=''), patch.object(clients, 'connect') as connect, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(clients.wizard()['status'], 'skipped')
            connect.assert_not_called()

    def test_wizard_only_connects_selected_client(self):
        with patch('sys.stdin.isatty', return_value=True), patch('builtins.input', return_value='2'), patch.object(clients, 'connect', return_value={'status': 'connected'}) as connect, contextlib.redirect_stdout(io.StringIO()):
            clients.wizard()
            connect.assert_called_once_with('codex')

    def test_clients_cli_is_read_only(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['sceneweaver-mcp', 'clients']), contextlib.redirect_stdout(output):
            main()
        self.assertEqual(len(json.loads(output.getvalue())), 2)
        self.assertFalse(self.target.parent.exists())

    def test_detection_uses_known_locations_without_reading_configs(self):
        with patch.object(Path, 'home', return_value=self.root), patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'custom'), 'APPDATA': str(self.root / 'roaming')}), patch.object(Path, 'open', side_effect=AssertionError('must not read configs')):
            # Call the actual function, not the discovery fixture used by registration tests.
            self.locations.stop()
            try:
                found = clients.discover()
            finally:
                self.locations.start()
        self.assertFalse(any(item['detected'] for item in found))
        self.assertEqual(found[0]['config_path'], str(self.root / 'custom/config.toml'))


if __name__ == '__main__':
    unittest.main()
