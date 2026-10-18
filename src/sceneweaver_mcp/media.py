"""Licensed catalog search, persistent caching, and managed local assets."""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from . import network
from .paths import home, contained, read_json, write_json

PROVIDERS = ('commons', 'openverse', 'pexels', 'library')
ID = re.compile(r'^[0-9a-f]{64}$')
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_SUFFIXES = {'.mp4', '.webm', '.ogv', '.mov'}
MAX_STORAGE_BYTES = 2 * 1024**3


def _folder(name):
    p = contained(home(), home() / name)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _text(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or '')))[:500]


def _reserve(size):
    directory = _folder('assets')
    total = sum(contained(directory, p).stat().st_size for p in directory.iterdir() if p.is_file())
    if total + size > MAX_STORAGE_BYTES:
        raise ValueError('Managed media cache exceeds 2 GiB; remove unused assets locally before importing more')
    if shutil.disk_usage(home()).free < size + 256 * 1024**2:
        raise ValueError('Keep at least 256 MiB free after importing media')


def _link(value):
    value = str(value or '')
    try:
        u = urlsplit(value)
        if u.scheme == 'https' and u.hostname and not u.username and not u.password and len(value) <= 4096:
            return value
    except ValueError:
        pass
    return ''


def _record(item):
    identity = item.get('url') or item.get('path')
    item['id'] = hashlib.sha256(str(identity).encode()).hexdigest()
    record = _folder('catalog') / (item['id'] + '.json')
    prior = read_json(record, {})
    if prior.get('path') and item.get('url') == prior.get('url'):
        item.update({k: prior[k] for k in ('path', 'sha256', 'quality') if k in prior})
    write_json(record, item)
    return item


def asset(asset_id: str) -> dict:
    if not isinstance(asset_id, str) or not ID.fullmatch(asset_id):
        raise ValueError('Invalid asset ID')
    item = read_json(_folder('catalog') / (asset_id + '.json'))
    if not isinstance(item, dict) or item.get('id') != asset_id:
        raise ValueError('Unknown asset ID; search or import it first')
    if item.get('path'):
        path = contained(_folder('assets'), Path(item['path']))
        if not path.is_file():
            raise ValueError('Managed asset is missing')
        item['path'] = str(path)
    return item


def _catalog_url(provider, query, kind):
    if provider == 'commons':
        params = {'action': 'query', 'format': 'json', 'formatversion': '2',
                  'generator': 'search', 'gsrsearch': query + (' filetype:video' if kind == 'video' else ''),
                  'gsrnamespace': '6', 'gsrlimit': '12', 'prop': 'imageinfo',
                  'iiprop': 'url|size|mime|extmetadata', 'iiurlwidth': '1920'}
        return 'https://commons.wikimedia.org/w/api.php?' + urlencode(params)
    return 'https://api.openverse.org/v1/images/?' + urlencode({
        'q': query, 'page_size': 12, 'license': 'cc0,pdm,by', 'source': 'flickr', 'mature': 'false'})


def _bridge(provider, query, kind):
    module = Path(os.environ['SCENEWEAVER_API_ANYTHING_MODULE']).expanduser().resolve()
    if not module.is_file() or module.name != 'index.js' or module.parent.name != 'dist':
        raise ValueError('API-Anything must point to an installed dist/index.js')
    node = shutil.which('node')
    if not node:
        raise ValueError('Node.js is required for API-Anything')
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'PATH', 'HOME', 'USERPROFILE', 'TEMP', 'TMP'}}
    env.update(SCENEWEAVER_API_ANYTHING_MODULE=str(module),
               API_ANYTHING_HOME=str(_folder('api-anything')))
    r = subprocess.run([node, str(Path(__file__).parent / 'integrations' / 'api_anything.mjs'),
                        provider, query, kind], capture_output=True, timeout=35, env=env,
                       stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if len(r.stdout) > 2 * 1024**2:
        raise ValueError('API-Anything output exceeds limit')
    try:
        result = json.loads(r.stdout)
    except (ValueError, UnicodeError):
        raise ValueError('API-Anything bridge failed') from None
    if not result.get('ok'):
        raise network.NetworkError('API-Anything provider stopped; no automatic retry',
                                   result.get('status', 'error'))
    return result['data']


def _normalize(provider, raw, query):
    found = []
    if provider == 'pexels':
        for row in raw if isinstance(raw, list) else []:
            value = row.get('download_url', '')
            match = re.fullmatch(r'(?:https://www\.pexels\.com)?/download/video/(\d{1,15})/?', value)
            if match:
                url = 'https://www.pexels.com/download/video/' + match[1] + '/'
                found.append(dict(url=url, page_url='https://www.pexels.com/video/' + match[1] + '/',
                                  preview_url='', kind='video', title=query, creator='',
                                  license='Pexels License', license_url='https://www.pexels.com/license/',
                                  width=0, height=0))
    elif provider == 'commons':
        for page in raw.get('query', {}).get('pages', []) or []:
            info = (page.get('imageinfo') or [{}])[0]
            md = info.get('extmetadata') or {}
            license_name = _text(md.get('LicenseShortName', {}).get('value', ''))
            if not (license_name in ('CC0', 'CC0 1.0', 'Public domain') or re.fullmatch(r'CC BY [1-4]\.0', license_name)):
                continue
            if md.get('Restrictions', {}).get('value'):
                continue
            mime = info.get('mime', '')
            if mime not in ('image/jpeg', 'image/png', 'image/webp', 'video/mp4', 'video/webm', 'video/ogg'):
                continue
            is_video = mime.startswith('video/')
            found.append(dict(url=info.get('url', ''),
                              page_url=info.get('descriptionurl', ''), preview_url=info.get('thumburl', ''),
                              kind='video' if is_video else 'image', title=_text(page.get('title')),
                              creator=_text(md.get('Artist', {}).get('value', '')),
                              attribution=_text(md.get('Attribution', {}).get('value', '')),
                              credit=_text(md.get('Credit', {}).get('value', '')),
                              license=license_name, license_url=_text(md.get('LicenseUrl', {}).get('value', '')),
                              width=info.get('width', 0), height=info.get('height', 0)))
    else:
        for row in raw.get('results', []):
            if row.get('license') not in ('cc0', 'pdm', 'by') or row.get('mature') is not False:
                continue
            found.append(dict(url=row.get('url', ''), page_url=row.get('foreign_landing_url', ''),
                              preview_url=row.get('thumbnail', ''), kind='image', title=_text(row.get('title')),
                              creator=_text(row.get('creator')), license=_text(row.get('license')),
                              license_url=_text(row.get('license_url')), width=row.get('width') or 0,
                              height=row.get('height') or 0))
    result = []
    for item in found[:12]:
        try:
            network.validate_url(item['url'])
            if provider != 'pexels' and min(int(item['width']), int(item['height'])) < 720:
                continue
        except (ValueError, TypeError):
            continue
        for field in ('page_url', 'license_url', 'preview_url'):
            item[field] = _link(item.get(field))
        if item['preview_url']:
            try:
                network.validate_url(item['preview_url'])
            except ValueError:
                item['preview_url'] = item['url'] if item['kind'] == 'image' else ''
        elif item['kind'] == 'image':
            item['preview_url'] = item['url']
        result.append(_record({**item, 'provider': provider, 'relevance_review_required': True}))
    return result


def search(query: str, providers: list[str] | None = None, kind: str = 'mixed', allow_network: bool = False) -> dict:
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 80 or any(ord(c) < 32 for c in query):
        raise ValueError('Query must contain 1–80 printable characters')
    providers = ['commons', 'openverse', 'library'] if providers is None else providers
    if not isinstance(providers, list) or not providers or len(providers) > 4 or any(p not in PROVIDERS for p in providers):
        raise ValueError('Unsupported providers')
    if kind not in ('mixed', 'image', 'video'):
        raise ValueError('Kind must be mixed, image, or video')
    assets, notices = [], []
    for provider in dict.fromkeys(providers):
        if provider == 'library':
            for p in _folder('catalog').glob('*.json'):
                item = read_json(p, {})
                if item.get('path') and query.casefold() in item.get('title', '').casefold():
                    try:
                        assets.append(asset(item['id']))
                    except ValueError:
                        pass
            continue
        if provider == 'openverse' and kind == 'video':
            notices.append({'provider': provider, 'status': 'images_only'})
            continue
        key = hashlib.sha256(f'{provider}:{kind}:{query.casefold()}'.encode()).hexdigest()
        cache_file = _folder('cache') / (key + '.json')
        cached = read_json(cache_file, {})
        if cached.get('expires', 0) > time.time():
            for item in cached.get('assets', []):
                try:
                    assets.append(asset(item['id']))
                except ValueError:
                    pass
            notices.append({'provider': provider, 'status': 'cached'})
            continue
        cooldown = read_json(_folder('cooldowns') / (provider + '.json'), {})
        if cooldown.get('until', 0) > time.time():
            notices.append({'provider': provider, 'status': cooldown.get('status'), 'retry': False,
                            'retry_after': cooldown['until']})
            continue
        if not allow_network:
            notices.append({'provider': provider, 'status': 'network_consent_required'})
            continue
        if provider == 'pexels' and not os.environ.get('SCENEWEAVER_API_ANYTHING_MODULE'):
            notices.append({'provider': provider, 'status': 'api_anything_not_configured'})
            continue
        try:
            via_bridge = bool(os.environ.get('SCENEWEAVER_API_ANYTHING_MODULE'))
            raw = _bridge(provider, query, kind) if via_bridge else network.fetch_json(_catalog_url(provider, query, kind))
            found = _normalize(provider, raw, query)
            assets.extend(found)
            write_json(cache_file, {'expires': time.time() + 86400, 'assets': found})
            notices.append({'provider': provider, 'status': 'ok',
                            'transport': 'api-anything' if via_bridge else 'direct_documented_api'})
        except Exception as exc:
            status = getattr(exc, 'status', 'error')
            delay = 86400 if status in ('auth', 'blocked') else 3600 if status == 'rate' else 60
            write_json(_folder('cooldowns') / (provider + '.json'), {'until': time.time() + delay, 'status': status})
            notices.append({'provider': provider, 'status': status, 'retry': False})
    return {'assets': list({a['id']: a for a in assets if kind == 'mixed' or a['kind'] == kind}.values()),
            'notices': notices}


def _inspect(path: Path, kind: str):
    if kind == 'image':
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = 40_000_000
        with Image.open(path) as img:
            if img.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Unsupported image format')
            width, height = img.size
            if width * height > 40_000_000 or min(width, height) < 720:
                raise ValueError('Image must be at least 720 pixels on its shorter side and below 40 megapixels')
            img.verify()
        return {'width': width, 'height': height}
    import imageio_ffmpeg
    import numpy as np
    reader = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgb24',
                                       input_params=['-protocol_whitelist', 'file,pipe', '-threads', '2'],
                                       output_params=['-vf', 'scale=64:64,fps=1', '-t', '4'])
    try:
        info = next(reader)
        width, height = info['source_size']
        duration = info.get('duration', 0)
        if min(width, height) < 720 or width * height > 8_500_000 or not 1 <= duration <= 600:
            raise ValueError('Video must be HD, below 8.5 megapixels, and 1–600 seconds')
        # shortcut: sampled motion detects frozen clips, semantic relevance still requires storyboard review.
        frames = [np.frombuffer(frame, dtype=np.uint8).astype(float) for frame in reader]
        motion = max((float(np.mean(np.abs(a - b))) for a, b in zip(frames, frames[1:])), default=0)
        if motion < .5:
            raise ValueError('Video appears frozen; choose a moving clip')
        return {'width': width, 'height': height, 'duration': duration, 'motion_score': round(motion, 2)}
    finally:
        reader.close()


def prepare(asset_id: str, allow_network: bool = False) -> dict:
    item = asset(asset_id)
    if item.get('path'):
        return item
    if not allow_network:
        raise ValueError('Network consent is required to download media')
    cooldown = read_json(_folder('cooldowns') / (item['provider'] + '.json'), {})
    if cooldown.get('until', 0) > time.time():
        raise ValueError('Provider is cooling down; choose another provider or a local asset')
    _reserve(0)
    try:
        body, mime = network.fetch(item['url'], limit=160 * 1024**2 if item['kind'] == 'video' else 25 * 1024**2)
    except network.NetworkError as exc:
        if exc.status in ('auth', 'blocked', 'rate'):
            write_json(_folder('cooldowns') / (item['provider'] + '.json'),
                       {'until': time.time() + (3600 if exc.status == 'rate' else 86400), 'status': exc.status})
        raise
    suffixes = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp',
                'video/mp4': '.mp4', 'video/webm': '.webm', 'video/ogg': '.ogv'}
    if mime not in suffixes or not mime.startswith(item['kind'] + '/'):
        raise ValueError('Provider returned an unexpected media type')
    digest = hashlib.sha256(body).hexdigest()
    path = contained(_folder('assets'), _folder('assets') / (digest + suffixes[mime]))
    _reserve(0 if path.exists() else len(body))
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.part')
    try:
        temporary.write_bytes(body)
        quality = _inspect(temporary, item['kind'])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    item.update(path=str(path.resolve()), sha256=digest, quality=quality)
    write_json(_folder('catalog') / (asset_id + '.json'), item)
    return item


def import_asset(filename: str, title: str, license_name: str = 'User supplied', creator: str = '') -> dict:
    if (not isinstance(filename, str) or not filename or Path(filename).name != filename
            or '/' in filename or '\\' in filename or ':' in filename):
        raise ValueError('Supply only a filename staged in the managed inbox')
    for value in (title, license_name, creator):
        if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value):
            raise ValueError('Metadata must contain at most 500 printable characters')
    if not title.strip() or not license_name.strip():
        raise ValueError('Title and license are required')
    source = contained(_folder('inbox'), _folder('inbox') / filename)
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 160 * 1024**2:
        raise ValueError('Missing, linked, or oversized inbox asset')
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
        raise ValueError('Unsupported media extension')
    kind = 'image' if suffix in IMAGE_SUFFIXES else 'video'
    quality = _inspect(source, kind)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    target = contained(_folder('assets'), _folder('assets') / (digest + suffix))
    _reserve(0 if target.exists() else source.stat().st_size)
    shutil.copyfile(source, target)
    return _record(dict(path=str(target.resolve()), sha256=digest, kind=kind, provider='library',
                        title=title, creator=creator, license=license_name, license_url='',
                        page_url='', preview_url='', width=quality['width'], height=quality['height'], quality=quality))
