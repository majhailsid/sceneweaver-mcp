import hashlib
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from sceneweaver_mcp import media, network


def commons(url='https://upload.wikimedia.org/test.jpg', license_name='CC BY 4.0'):
    return {'query': {'pages': [{'title': 'File:Tree', 'imageinfo': [{
        'url': url, 'descriptionurl': 'https://commons.wikimedia.org/wiki/File:Tree',
        'width': 1920, 'height': 1080, 'mime': 'image/jpeg', 'extmetadata': {
            'LicenseShortName': {'value': license_name},
            'LicenseUrl': {'value': 'https://creativecommons.org/licenses/by/4.0/'},
            'Artist': {'value': '<b>Photographer</b>'}}}]}]}}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.home = patch.object(media, 'home', return_value=self.root)
        self.home.start()
        self.env = patch.dict('os.environ', {'SCENEWEAVER_API_ANYTHING_MODULE': '', 'SCENEWEAVER_HOME': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.home.stop()
        self.temp.cleanup()

    def test_network_is_opt_in(self):
        with patch.object(network, 'fetch_json') as fetch:
            result = media.search('tree', ['commons'])
            fetch.assert_not_called()
        self.assertEqual(result['assets'], [])
        self.assertEqual(result['notices'][0]['status'], 'network_consent_required')

    def test_search_cache_survives_calls_and_keeps_attribution(self):
        with patch.object(network, 'fetch_json', return_value=commons()) as fetch:
            first = media.search('tree', ['commons'], allow_network=True)
            second = media.search('tree', ['commons'], allow_network=False)
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first['assets'], second['assets'])
        self.assertEqual(first['assets'][0]['creator'], 'Photographer')
        self.assertEqual(second['notices'][0]['status'], 'cached')
        self.assertEqual(first['notices'][0]['transport'], 'direct_documented_api')
        self.assertEqual(media.asset(first['assets'][0]['id'])['license'], 'CC BY 4.0')

    def test_blocked_provider_does_not_retry_different_query(self):
        with patch.object(network, 'fetch_json', side_effect=network.NetworkError('blocked', 'blocked')) as fetch:
            first = media.search('one', ['commons'], allow_network=True)
            second = media.search('two', ['commons'], allow_network=True)
            self.assertEqual(fetch.call_count, 1)
        self.assertFalse(first['notices'][0]['retry'])
        self.assertEqual(second['notices'][0]['status'], 'blocked')

    def test_restrictive_license_and_private_media_url_are_excluded(self):
        self.assertEqual(media._normalize('commons', commons(license_name='CC BY-SA 4.0'), 'tree'), [])
        self.assertEqual(media._normalize('commons', commons(url='https://127.0.0.1/tree.jpg'), 'tree'), [])

    def test_commons_external_thumbnail_keeps_approved_original_and_credit(self):
        raw = commons()
        info = raw['query']['pages'][0]['imageinfo'][0]
        info['thumburl'] = 'https://thumb.wikimedia.org/new-host/tree.jpg'
        info['extmetadata'].update(Attribution={'value': 'Required attribution'}, Credit={'value': 'Original collection'})
        result = media._normalize('commons', raw, 'tree')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['url'], 'https://upload.wikimedia.org/test.jpg')
        self.assertEqual(result[0]['preview_url'], result[0]['url'])
        self.assertEqual(result[0]['attribution'], 'Required attribution')
        self.assertEqual(result[0]['credit'], 'Original collection')

    def test_optional_pexels_does_not_fall_back_to_scraping(self):
        with patch.object(network, 'fetch_json') as fetch:
            result = media.search('tree', ['pexels'], allow_network=True)
            fetch.assert_not_called()
        self.assertEqual(result['notices'][0]['status'], 'api_anything_not_configured')

    def test_invalid_tools_inputs(self):
        for value in ('../secret', 'a' * 63, 'Z' * 64):
            with self.assertRaises(ValueError):
                media.asset(value)
        for filename in ('../secret.jpg', 'C:\\secret.jpg', 'sub/image.jpg', 'sub\\image.jpg'):
            with self.assertRaises(ValueError):
                media.import_asset(filename, 'Tree')
        with self.assertRaises(ValueError):
            media.search('tree', ['unknown'])

    def test_import_and_prepare_use_managed_hash_store(self):
        from PIL import Image
        inbox = media._folder('inbox')
        source = inbox / 'tree.png'
        Image.new('RGB', (1280, 720), 'green').save(source)
        result = media.import_asset('tree.png', 'Tree', 'CC0', 'Local creator')
        self.assertEqual(result['provider'], 'library')
        self.assertTrue(Path(result['path']).is_relative_to(self.root / 'assets'))
        self.assertEqual(result['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(media.prepare(result['id']), result)
        self.assertEqual(media.search('tree', ['library'])['assets'], [result])

    def test_low_resolution_import_is_rejected(self):
        from PIL import Image
        Image.new('RGB', (80, 80)).save(media._folder('inbox') / 'tiny.png')
        with self.assertRaises(ValueError):
            media.import_asset('tiny.png', 'Tiny')

    def test_managed_asset_quota_is_enforced(self):
        from PIL import Image
        Image.new('RGB', (1280, 720)).save(media._folder('inbox') / 'tree.png')
        with patch.object(media, 'MAX_STORAGE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'cache exceeds'):
                media.import_asset('tree.png', 'Tree')
        self.assertEqual(list(media._folder('assets').iterdir()), [])

    def test_prepare_consent_and_byte_type_checks(self):
        item = media._normalize('commons', commons(), 'tree')[0]
        with self.assertRaises(ValueError):
            media.prepare(item['id'])
        with patch.object(network, 'fetch', return_value=(b'<html>challenge</html>', 'text/html')):
            with self.assertRaises(ValueError):
                media.prepare(item['id'], True)
        self.assertEqual(list(media._folder('assets').iterdir()), [])

    def test_deny_private_dns_and_unapproved_hosts(self):
        for url in ('http://upload.wikimedia.org/a.jpg', 'https://evil.example/a.jpg',
                    'https://user:pass@upload.wikimedia.org/a.jpg', 'https://upload.wikimedia.org:444/a.jpg'):
            with self.assertRaises(network.NetworkError):
                network.validate_url(url)
        with patch.object(socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(network.NetworkError):
                network.public_addresses('upload.wikimedia.org')

    def test_video_motion_quality_with_real_ffmpeg(self):
        import imageio_ffmpeg
        import numpy as np
        for moving in (False, True):
            path = self.root / ('moving.mp4' if moving else 'frozen.mp4')
            writer = imageio_ffmpeg.write_frames(str(path), (1280, 720), fps=2,
                                                 output_params=['-threads', '2'])
            writer.send(None)
            try:
                for frame in range(6):
                    writer.send(np.full((720, 1280, 3), frame * 30 if moving else 80, dtype=np.uint8))
            finally:
                writer.close()
            if moving:
                self.assertGreater(media._inspect(path, 'video')['motion_score'], 1)
            else:
                with self.assertRaisesRegex(ValueError, 'frozen'):
                    media._inspect(path, 'video')

    def test_one_second_moving_video_is_accepted(self):
        import imageio_ffmpeg
        import numpy as np
        path = self.root / 'short-moving.mp4'
        writer = imageio_ffmpeg.write_frames(str(path), (1280, 720), fps=4,
                                             output_params=['-threads', '2'])
        writer.send(None)
        try:
            for frame in range(4):
                writer.send(np.full((720, 1280, 3), frame * 50, dtype=np.uint8))
        finally:
            writer.close()
        self.assertGreater(media._inspect(path, 'video')['motion_score'], 1)


if __name__ == '__main__':
    unittest.main()
