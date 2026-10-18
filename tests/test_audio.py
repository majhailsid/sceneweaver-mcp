import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

import numpy as np

from sceneweaver_mcp import audio


class FakeVoice:
    def create(self, text, **kwargs):
        return np.sin(np.arange(2400) / 20).astype('float32') * .1, 24000


class AudioTests(unittest.TestCase):
    def test_measured_sentence_cues_and_wave(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(audio, '_engine', return_value=FakeVoice()):
            result = audio.synthesize('First sentence. Second sentence!', 'af_heart', Path(directory) / 'voice.wav')
            self.assertEqual(len(result['cues']), 2)
            self.assertAlmostEqual(result['cues'][0]['end'], .1)
            self.assertAlmostEqual(result['cues'][1]['start'], .26)
            self.assertAlmostEqual(result['duration'], .36)
            with wave.open(result['path']) as stream:
                self.assertAlmostEqual(stream.getnframes() / stream.getframerate(), result['duration'])

    def test_model_hashes_are_pinned(self):
        for _, (_, digest) in audio.MODELS.items():
            self.assertEqual(len(digest), 64)
            int(digest, 16)

    def test_invalid_voice_and_provider_fail_without_fallback(self):
        for voice, provider in [('unknown', 'kokoro'), ('af_heart', 'unknown')]:
            with self.assertRaises(ValueError):
                audio.synthesize('Hello.', voice, Path('unused.wav'), provider=provider)

    def test_music_is_stereo_bounded_and_faded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = audio.create_music(Path(directory) / 'music.wav', 2)
            with wave.open(str(path)) as stream:
                self.assertEqual(stream.getnchannels(), 2)
                self.assertEqual(stream.getnframes(), 48000)
                samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2')
            self.assertLessEqual(np.max(np.abs(samples.astype('int32'))), round(.601 * 32767))
            self.assertEqual(samples[0], 0)
        filters = audio.music_filter(.1)
        self.assertIn('sidechaincompress', filters)
        self.assertIn('alimiter', filters)
        with self.assertRaises(ValueError):
            audio.music_filter(2)


if __name__ == '__main__':
    unittest.main()
