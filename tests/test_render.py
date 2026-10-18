import tempfile
import unittest
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from sceneweaver_mcp import audio, render


def fake_speech(text, voice, output, **kwargs):
    rate = 24000
    samples = .1 * np.sin(np.arange(rate // 2) * 2 * np.pi * 200 / rate)
    audio.write_wave(output, samples, rate)
    return {'path': str(output), 'duration': .5,
            'cues': [{'text': text, 'start': 0, 'end': .5}]}


class RenderTests(unittest.TestCase):
    def test_brand_background_has_readable_text(self):
        with tempfile.TemporaryDirectory() as directory:
            for color, expected in [('#153D2D', '#ffffff'), ('#eeeeee', '#000000')]:
                foreground, background = render._brand_colors(color)
                self.assertEqual(foreground, expected)
                path = Path(directory) / 'title.png'
                render._card('Readable title', path, 600, 42, foreground, background)
                with Image.open(path) as image:
                    self.assertEqual(image.getpixel((image.width // 2, 3)), background)

    def test_every_ffmpeg_input_restricts_protocols(self):
        with patch('imageio_ffmpeg.get_ffmpeg_exe', return_value='ffmpeg'), \
                patch('sceneweaver_mcp.render.subprocess.run') as run:
            run.return_value.returncode = 0
            render._run(['-i', 'one.mp4', '-loop', '1', '-i', 'two.png', 'out.mp4'])
            arguments = run.call_args.args[0]
            self.assertEqual(run.call_args.kwargs['creationflags'],getattr(subprocess,'CREATE_NO_WINDOW',0))
            for index, argument in enumerate(arguments):
                if argument == '-i':
                    self.assertEqual(arguments[index - 2:index], ['-protocol_whitelist', 'file,pipe'])

    def test_narration_fits_without_cutting_speech(self):
        self.assertEqual(render._tempo(1, 2), 1)
        self.assertEqual(render._tempo(2.4, 2), 1.2)
        with self.assertRaisesRegex(ValueError, 'too long'):
            render._tempo(3, 2)

    def test_phrase_and_word_timing_is_explicitly_estimated(self):
        original = [{'text': 'One two three four five six seven eight.', 'start': 2, 'end': 6}]
        for style, count in [('phrase', 2), ('word', 8), ('sentence', 1)]:
            cues = render.caption_cues(original, style)
            self.assertEqual(len(cues), count)
            self.assertEqual(cues[0]['start'], 2)
            self.assertEqual(cues[-1]['end'], 6)
            self.assertEqual(cues[0]['timing'], 'measured_sentence' if style == 'sentence'
                             else 'estimated_within_measured_sentence')
            self.assertTrue(all(a['end'] <= b['start'] for a, b in zip(cues, cues[1:])))

    def test_short_footage_is_not_frozen_or_recycled(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = {'voice': 'af_heart', 'caption_style': 'phrase'}
            scene = {'text': 'A clear explanation.', 'asset_id': 'short'}
            with patch.object(audio, 'synthesize', side_effect=fake_speech), \
                    patch.object(render, 'probe', return_value={'duration': .5}):
                with self.assertRaisesRegex(ValueError, 'shorter than the scene'):
                    render._scene(scene, plan, {'kind': 'video', 'path': 'short.mp4'},
                                  Path(directory), 0, 1, (1080, 1080), [], lambda *args: None)

    def test_exact_duration_captioned_music_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'image.png'
            Image.new('RGB', (1200, 1200), '#356b77').save(source)
            plan = {'id': 'test', 'duration_seconds': 2, 'aspect': '1:1', 'voice': 'af_heart',
                    'music': 'ambient', 'music_volume': .1, 'caption_style': 'phrase',
                    'branding': {'title': 'A clear explanation', 'footer': 'SceneWeaver'},
                    'scenes': [{'id': 'one', 'text': 'A short measured sentence.',
                                'duration_seconds': 1, 'asset_id': 'one'},
                               {'id': 'two', 'text': 'Another useful sentence.',
                                'duration_seconds': 1, 'asset_id': 'two'}]}
            with patch.dict(os.environ, {'SCENEWEAVER_HOME': str(root)}), patch('sceneweaver_mcp.media.prepare', return_value={
                'path': str(source), 'kind': 'image', 'credit': 'Own work',
                'creator': 'Test creator', 'license': 'CC BY 4.0',
                'license_url': 'https://creativecommons.org/licenses/by/4.0/',
                'page_url': 'https://example.com/source', 'attribution': 'Required attribution'}), \
                    patch.object(audio, 'synthesize', side_effect=fake_speech):
                result = render.render_storyboard(plan, root / 'result', lambda *args: None)
            self.assertTrue(Path(result['video']).is_file())
            self.assertAlmostEqual(result['duration_seconds'], 2, delta=.075)
            self.assertEqual(result['resolution'], [1080, 1080])
            self.assertTrue(result['report']['music_ducking'])
            self.assertEqual(result['report']['alignment'], 'estimated_within_measured_sentence')
            self.assertEqual(len(result['credits']), 2)
            credit = result['credits'][0]
            self.assertEqual(credit['credit'], 'Own work')
            self.assertEqual(credit['creator'], 'Test creator')
            self.assertEqual(credit['license'], 'CC BY 4.0')
            self.assertEqual(credit['page_url'], 'https://example.com/source')
            self.assertEqual(credit['attribution'], 'Required attribution')
            self.assertIn('changes', credit)
            metadata = render.probe(Path(result['video']))
            self.assertIn('audio_codec', metadata)


if __name__ == '__main__':
    unittest.main()
