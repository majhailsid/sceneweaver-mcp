"""Local narration with measured sentence cues and an original instrumental bed."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlsplit
import wave

from .paths import home, contained

VOICES = ('af_heart', 'af_bella', 'am_michael', 'bf_emma')
MODEL_BASE = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'
MODELS = {
    'kokoro-v1.0.onnx': (325532387, '7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5'),
    'voices-v1.0.bin': (28214398, 'bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d'),
}


def _model_directory() -> Path:
    root = home()
    return contained(root, root / 'models' / 'kokoro')


def capabilities() -> dict:
    installed = importlib.util.find_spec('kokoro_onnx') is not None
    ready = installed and all((_model_directory() / name).is_file() for name in MODELS)
    return {'kokoro': {'installed': installed, 'ready': ready, 'local': True,
                       'api_key': False, 'voices': list(VOICES)},
            'caption_alignment': 'Measured sentence boundaries; finer display timing is estimated by the renderer.',
            'fallback_policy': 'An unavailable selected voice fails; no silent substitution.',
            'music': ['ambient', 'none']}


def _valid_model(path: Path, size: int, digest: str) -> bool:
    if not path.is_file() or path.stat().st_size != size:
        return False
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest() == digest


def setup_voice() -> dict:
    """Explicit CLI setup only: download pinned, integrity-checked model assets."""
    directory = _model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    class ModelRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, newurl):
            parsed = urlsplit(newurl)
            if parsed.scheme != 'https' or parsed.hostname not in {
                'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
                raise ValueError('Unexpected voice model download host')
            return super().redirect_request(request, fp, code, message, headers, newurl)

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), ModelRedirect())
    for name, (size, digest) in MODELS.items():
        target = contained(home(), directory / name)
        if _valid_model(target, size, digest):
            continue
        partial = contained(home(), target.with_suffix('.download'))
        try:
            request = urllib.request.Request(MODEL_BASE + name, headers={'User-Agent': 'SceneWeaver-MCP/0.1'})
            with opener.open(request, timeout=90) as response, partial.open('wb') as stream:
                if not response.url.startswith('https://'):
                    raise ValueError('Voice model download requires HTTPS')
                received = 0
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > size:
                        raise ValueError('Voice model exceeds pinned size')
                    stream.write(chunk)
            if not _valid_model(partial, size, digest):
                raise ValueError('Voice model integrity check failed')
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    _engine.cache_clear()
    return capabilities()


@lru_cache(maxsize=1)
def _engine():
    if not capabilities()['kokoro']['ready']:
        raise ValueError('Kokoro is not ready. Install the voice extra and run setup-voice first.')
    for name, (size, digest) in MODELS.items():
        if not _valid_model(_model_directory() / name, size, digest):
            raise ValueError('Voice model integrity check failed. Run setup-voice to repair.')
    import onnxruntime as ort
    import tempfile
    temporary = contained(home(), home() / 'temp')
    temporary.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(temporary)
    from kokoro_onnx import Kokoro
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(_model_directory() / 'kokoro-v1.0.onnx'),
                                   sess_options=options, providers=['CPUExecutionProvider'])
    return Kokoro.from_session(session, str(_model_directory() / 'voices-v1.0.bin'))


def write_wave(path: Path, samples, rate: int = 24000) -> None:
    import numpy as np
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim not in (1, 2) or not len(samples) or not np.isfinite(samples).all():
        raise ValueError('Invalid audio samples')
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())


def synthesize(text: str, voice: str, output: Path, speed: float = 1.0,
               provider: str = 'kokoro') -> dict:
    import numpy as np
    if provider != 'kokoro':
        raise ValueError('Unsupported voice provider; use local kokoro. No silent fallback is allowed.')
    if voice not in VOICES or not .75 <= speed <= 1.25:
        raise ValueError('Unsupported voice or speed')
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError('Narration must contain 1 to 12000 characters')
    engine = _engine()
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]
    chunks, cues, position, sample_rate = [], [], 0.0, None
    for index, sentence in enumerate(sentences):
        samples, rate = engine.create(sentence, voice=voice, speed=speed,
                                      lang='en-gb' if voice.startswith('b') else 'en-us')
        samples = np.asarray(samples, dtype=np.float32)
        if sample_rate is not None and rate != sample_rate:
            raise ValueError('Voice provider changed the audio sample rate')
        if samples.ndim != 1 or not len(samples) or not np.isfinite(samples).all():
            raise ValueError('Voice provider returned invalid audio')
        sample_rate = rate
        duration = len(samples) / rate
        cues.append({'text': sentence, 'start': position, 'end': position + duration})
        chunks.append(samples)
        position += duration
        if index < len(sentences) - 1:
            pause = np.zeros(round(rate * .16), dtype=np.float32)
            chunks.append(pause)
            position += len(pause) / rate
        if position > 150:
            raise ValueError('Narration is too long; shorten the script')
    write_wave(Path(output), np.concatenate(chunks), sample_rate)
    return {'path': str(output), 'duration': position, 'cues': cues,
            'alignment': 'sentence', 'provider': provider, 'voice': voice}


def create_music(path: Path, duration: float) -> Path:
    """Generate an original warm pad and pulse; no external recording or licence."""
    import numpy as np
    if not 0 < duration <= 120:
        raise ValueError('Music duration must be between 0 and 120 seconds')
    rate = 24000
    t = np.arange(math.ceil(duration * rate)) / rate
    signal = np.zeros_like(t)
    chords = [(130.81, 164.81, 196), (110, 130.81, 164.81),
              (87.31, 110, 130.81), (98, 123.47, 146.83)]
    for start in range(0, math.ceil(duration), 4):
        mask = (t >= start) & (t < start + 4)
        u = t[mask] - start
        envelope = np.minimum(u / .5, 1) * np.minimum((4 - u) / .8, 1)
        for frequency in chords[(start // 4) % 4]:
            signal[mask] += .10 * envelope * (np.sin(2 * np.pi * frequency * u)
                                            + .15 * np.sin(4 * np.pi * frequency * u))
    for beat in np.arange(0, duration, .75):
        mask = (t >= beat) & (t < beat + .3)
        u = t[mask] - beat
        signal[mask] += .025 * np.exp(-u * 18) * np.sin(2 * np.pi * 523.25 * u)
    fade = np.minimum(t / 1.5, 1) * np.minimum(np.maximum(duration - t, 0) / 2, 1)
    signal *= fade
    signal *= .6 / max(float(np.max(np.abs(signal))), .001)
    write_wave(path, np.column_stack((signal, signal)), rate)
    return path


def music_filter(level: float = .1) -> str:
    if not 0 <= level <= .3:
        raise ValueError('Background music volume must be between 0 and 0.3')
    return (f'[0:a]asplit=2[voice][control];[1:a]volume={level}[bed];'
            '[bed][control]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=500[ducked];'
            '[voice][ducked]amix=inputs=2:duration=first:normalize=0,'
            'alimiter=limit=0.95:latency=1[outa]')
