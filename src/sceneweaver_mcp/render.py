"""Bounded scene-by-scene FFmpeg export with local narration and captions."""
from __future__ import annotations

import math
from pathlib import Path
import subprocess

from . import audio
from .paths import write_json


def _run(arguments: list[str], timeout: int = 240) -> None:
    import imageio_ffmpeg
    safe_arguments = []
    for argument in arguments:
        if argument == '-i':
            safe_arguments += ['-protocol_whitelist', 'file,pipe']
        safe_arguments.append(argument)
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner',
                             '-loglevel', 'error', '-y', *safe_arguments],
                            capture_output=True, timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        # Keep local paths, source URLs and provider messages out of tool responses.
        raise ValueError('Media export failed; check the selected asset format and available disk space')


def probe(path: Path) -> dict:
    import imageio_ffmpeg
    reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb24',
                                       input_params=['-protocol_whitelist', 'file,pipe'])
    try:
        return next(reader)
    finally:
        reader.close()


def _font(size: int):
    from PIL import ImageFont
    candidates = ('C:/Windows/Fonts/arialbd.ttf',
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                  '/System/Library/Fonts/Supplemental/Arial Bold.ttf')
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _card(text: str, path: Path, width: int, size: int, color: str = '#ffffff',
          background=(10, 18, 28, 215)) -> tuple[int, int]:
    from PIL import Image, ImageDraw
    font = _font(size)
    canvas = Image.new('RGBA', (width, 1))
    draw = ImageDraw.Draw(canvas)
    words = text.split()
    lines, current = [], ''
    for word in words:
        proposed = f'{current} {word}'.strip()
        if draw.textlength(proposed, font=font) <= width - 64:
            current = proposed
        else:
            if current:
                lines.append(current)
            current = word
            if draw.textlength(word, font=font) > width - 64:
                raise ValueError('Caption or branding contains a word too long to display')
    if current:
        lines.append(current)
    if not lines or len(lines) > 6:
        raise ValueError('Caption is too long; split this scene into shorter sentences')
    line_height = math.ceil(size * 1.3)
    height = len(lines) * line_height + 42
    canvas = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=20, fill=background)
    for index, line in enumerate(lines):
        draw.text((width / 2, 20 + index * line_height), line, font=font,
                  fill=color, anchor='mt', stroke_width=1, stroke_fill=(0, 0, 0, 180))
    canvas.save(path)
    return width, height


def _brand_colors(color: str) -> tuple[str, tuple[int, int, int, int]]:
    from PIL import ImageColor
    red, green, blue = ImageColor.getrgb(color)
    text = '#000000' if .299 * red + .587 * green + .114 * blue >= 150 else '#ffffff'
    return text, (red, green, blue, 255)


def _tempo(duration: float, target: float) -> float:
    if not math.isfinite(duration) or duration <= 0 or target <= 0:
        raise ValueError('Invalid narration duration')
    ratio = duration / target
    if ratio > 1.25:
        raise ValueError('Narration is too long for this scene. Shorten its text or increase its duration.')
    # Short speech keeps its natural pace; quiet breathing room is better than dragging words.
    return max(1.0, ratio)


def caption_cues(cues: list[dict], style: str) -> list[dict]:
    """Keep measured boundaries; optional finer display timing is explicitly estimated."""
    if style == 'sentence':
        return [{**cue, 'timing': 'measured_sentence'} for cue in cues]
    if style not in ('phrase', 'word'):
        raise ValueError('Unknown caption style')
    result = []
    for cue in cues:
        words = cue['text'].split()
        if not words:
            continue
        weights = [max(len(word), 2) for word in words]
        weight_sum = sum(weights)
        elapsed = 0
        chunk_size = 1 if style == 'word' else 6
        for offset in range(0, len(words), chunk_size):
            group = words[offset:offset + chunk_size]
            weight = sum(weights[offset:offset + chunk_size])
            start = cue['start'] + (cue['end'] - cue['start']) * elapsed / weight_sum
            elapsed += weight
            end = cue['start'] + (cue['end'] - cue['start']) * elapsed / weight_sum
            result.append({'text': ' '.join(group), 'start': start, 'end': end,
                           'timing': 'estimated_within_measured_sentence'})
    return result


def _credit(asset: dict, changes: str) -> dict:
    result = {key: asset.get(key, '') for key in
              ('id', 'provider', 'title', 'creator', 'license', 'license_url', 'page_url',
               'attribution', 'credit')}
    result['changes'] = changes
    return result


def _scene(scene: dict, plan: dict, asset: dict, output: Path, index: int,
           duration: float, resolution: tuple[int, int], branding: list[dict],
           progress) -> dict:
    width, height = resolution
    narration = audio.synthesize(scene['text'], plan.get('voice', 'af_heart'),
                                 output / f'speech-{index}.wav',
                                 provider=plan.get('voice_provider', 'kokoro'))
    tempo = _tempo(narration['duration'], duration)
    cues = caption_cues([{**cue, 'start': cue['start'] / tempo, 'end': cue['end'] / tempo}
                         for cue in narration['cues']], plan.get('caption_style', 'phrase'))
    arguments = []
    if asset['kind'] == 'image':
        arguments += ['-loop', '1', '-framerate', '30']
    elif asset['kind'] != 'video':
        raise ValueError('Selected scene asset must be an image or video')
    source = Path(asset['path'])
    if asset['kind'] == 'video' and probe(source).get('duration', 0) + .04 < duration:
        raise ValueError('Selected video is shorter than the scene; choose another asset or shorten the scene')
    arguments += ['-i', str(source), '-i', narration['path']]
    overlays = list(branding)
    caption_size = 42 if width == 1080 else 44
    for cue_index, cue in enumerate(cues):
        card = output / f'caption-{index}-{cue_index}.png'
        _, card_height = _card(cue['text'], card, width - 120, caption_size,
                               '#70e5df' if plan.get('caption_style') == 'word' else '#ffffff')
        caption_y = height - 160 - card_height
        if caption_y < height * .45:
            raise ValueError('Caption overlaps the title safe area; shorten this sentence')
        overlays.append({'path': card, 'x': 60, 'y': caption_y,
                         'start': cue['start'], 'end': cue['end']})
    for item in overlays:
        arguments += ['-loop', '1', '-framerate', '30', '-i', str(item['path'])]
    base = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1')
    if asset['kind'] == 'image':
        base += (f",zoompan=z='min(max(zoom,pzoom)+0.00025,1.045)':x='iw/2-iw/zoom/2':"
                 f"y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=30")
    else:
        base += ',fps=30,setpts=PTS-STARTPTS'
    filters = [f'[0:v]{base}[v0]']
    for overlay_index, item in enumerate(overlays):
        active = ''
        if 'start' in item:
            active = f":enable='between(t,{item['start']:.6f},{item['end']:.6f})'"
        filters.append(f"[v{overlay_index}][{overlay_index + 2}:v]overlay="
                       f"{item['x']}:{item['y']}:eof_action=repeat{active}[v{overlay_index + 1}]")
    filters.append(f'[1:a]atempo={tempo:.9f},apad,atrim=duration={duration:.9f},'
                   'asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-2:LRA=7[a]')
    target = output / f'scene-{index}.mkv'
    arguments += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(filters),
                  '-map', f'[v{len(overlays)}]', '-map', '[a]', '-t', f'{duration:.9f}',
                  '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                  '-pix_fmt', 'yuv420p', '-threads', '2', '-c:a', 'pcm_s16le',
                  '-ar', '48000', '-ac', '2', str(target)]
    progress('rendering_scene', index)
    _run(arguments)
    return {'path': str(target), 'cues': cues, 'narration_duration': narration['duration'],
            'tempo': tempo, 'duration': duration, 'asset_id': scene['asset_id']}


def _branding(plan: dict, output: Path, resolution: tuple[int, int], allow_network: bool) -> list[dict]:
    from PIL import Image
    from . import media
    width, height = resolution
    branding = plan.get('branding') or {}
    overlays = []
    if branding.get('title'):
        card = output / 'brand-title.png'
        text_color, background = _brand_colors(branding.get('color', '#153D2D'))
        _, card_height = _card(branding['title'], card, width - 120, 42,
                               text_color, background)
        if card_height > height * .25:
            raise ValueError('Brand title is too long for the safe area')
        overlays.append({'path': card, 'x': 60, 'y': 42})
    if branding.get('footer'):
        card = output / 'brand-footer.png'
        _, card_height = _card(branding['footer'], card, width - 120, 26)
        if card_height > 100:
            raise ValueError('Brand footer must fit on one line')
        overlays.append({'path': card, 'x': 60, 'y': height - card_height - 25})
    if branding.get('logo_asset_id'):
        asset = media.prepare(branding['logo_asset_id'], allow_network=allow_network)
        if asset['kind'] != 'image':
            raise ValueError('Brand logo must be an image')
        logo = output / 'brand-logo.png'
        with Image.open(asset['path']) as image:
            image = image.convert('RGBA')
            image.thumbnail((140, 140))
            image.save(logo)
        overlays.append({'path': logo, 'x': width - 190, 'y': height // 3,
                         'credit': _credit(asset, 'Resized and overlaid as a logo.')})
    return overlays


def render_storyboard(plan: dict, output_dir: Path, progress, allow_network: bool = False) -> dict:
    from . import media
    if plan.get('voice_provider', 'kokoro') != 'kokoro':
        raise ValueError('Only the installed local Kokoro provider is available for rendering')
    resolution = {'16:9': (1920, 1080), '9:16': (1080, 1920), '1:1': (1080, 1080)}[plan['aspect']]
    requested = float(plan['duration_seconds'])
    if not math.isfinite(requested) or not 1 <= requested <= 120:
        raise ValueError('Duration must be between 1 and 120 seconds')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    overlays = _branding(plan, output_dir, resolution, allow_network)
    scenes = []
    credits = [item['credit'] for item in overlays if 'credit' in item]
    elapsed, frames = 0.0, 0
    for index, scene in enumerate(plan['scenes']):
        elapsed += scene['duration_seconds']
        end_frame = round(elapsed * 30)
        duration = (end_frame - frames) / 30
        frames = end_frame
        if duration <= 0:
            raise ValueError('Every scene must contain at least one video frame')
        asset = media.prepare(scene['asset_id'], allow_network=allow_network)
        changes = 'Shortened or fitted; narration and captions added.'
        if plan.get('music', 'ambient') == 'ambient' and plan.get('music_volume', .1) > 0:
            changes += ' Background music added.'
        credits.append(_credit(asset, changes))
        extra_credits = asset.get('credits')
        if isinstance(extra_credits, list):
            credits.extend(item for item in extra_credits if isinstance(item, dict))
        scenes.append(_scene(scene, plan, asset, output_dir, index, duration, resolution, overlays, progress))
    if not scenes or abs(elapsed - requested) > .04:
        raise ValueError('Scene durations must add up to the requested duration')
    concat = output_dir / 'scenes.txt'
    # These generated filenames contain no user text or arbitrary filesystem paths.
    concat.write_text(''.join(f"file 'scene-{index}.mkv'\n" for index in range(len(scenes))), encoding='utf-8')
    silent_bed = output_dir / 'narrated.mkv'
    progress('joining_scenes', len(scenes))
    _run(['-f', 'concat', '-safe', '1', '-i', str(concat), '-c', 'copy',
          '-t', str(requested), str(silent_bed)])
    final = output_dir / 'video.mp4'
    if plan.get('music', 'ambient') == 'ambient' and plan.get('music_volume', .1) > 0:
        music = audio.create_music(output_dir / 'original-ambient.wav', requested)
        progress('mixing_music', len(scenes))
        _run(['-i', str(silent_bed), '-i', str(music), '-filter_complex_threads', '1',
              '-filter_complex', audio.music_filter(plan.get('music_volume', .1)),
              '-map', '0:v', '-map', '[outa]', '-c:v', 'copy', '-c:a', 'aac',
              '-b:a', '192k', '-t', str(requested), '-movflags', '+faststart', str(final)])
    else:
        _run(['-i', str(silent_bed), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
              '-t', str(requested), '-movflags', '+faststart', str(final)])
    metadata = probe(final)
    actual = metadata['duration']
    if abs(actual - requested) > .075 or tuple(metadata['size']) != resolution:
        final.unlink(missing_ok=True)
        raise ValueError('Rendered output failed its duration or resolution check')
    report = {'duration_seconds': actual, 'requested_duration_seconds': requested,
              'resolution': list(resolution), 'fps': 30, 'voice_provider': 'kokoro',
              'voice': plan.get('voice', 'af_heart'), 'music': plan.get('music', 'ambient'),
              'music_ducking': plan.get('music', 'ambient') == 'ambient' and plan.get('music_volume', .1) > 0,
              'requested_caption_style': plan.get('caption_style', 'phrase'),
              'effective_caption_style': plan.get('caption_style', 'phrase'),
              'alignment': ('measured_sentence' if plan.get('caption_style', 'phrase') == 'sentence'
                            else 'estimated_within_measured_sentence'),
              'voice_fallback_used': False, 'scenes': scenes,
              'semantic_review': 'Selected assets still require human review for subject relevance.'}
    write_json(output_dir / 'report.json', report)
    write_json(output_dir / 'credits.json', credits)
    return {'video': str(final), 'duration_seconds': actual,
            'resolution': list(resolution), 'credits': credits, 'report': report}
