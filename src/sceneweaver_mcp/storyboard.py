"""Explicit sentence-to-scene plans and editable asset choices."""
from __future__ import annotations

import math
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from .paths import home, contained, identifier, read_json, write_json


def _text(value, name, maximum, required=False):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\r\t' for c in value):
        raise ValueError(f'Invalid {name}')
    if required and not value.strip():
        raise ValueError(f'{name} is required')
    return value.strip()


def _asset_id(value):
    if value is not None and (not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value)):
        raise ValueError('Invalid asset identifier')
    return value


def create(scenes: list[dict], duration_seconds: float=30, aspect='9:16', voice='af_heart',
           voice_provider='kokoro', music='ambient', music_volume=.1, branding=None,
           caption_style='phrase') -> dict:
    if not isinstance(scenes,list) or not 1<=len(scenes)<=30:
        raise ValueError('Supply 1–30 assistant-written scenes')
    if type(duration_seconds) not in (int,float) or not math.isfinite(duration_seconds) or not 1<=duration_seconds<=120:
        raise ValueError('Duration must be 1–120 seconds')
    if aspect not in ('9:16','16:9','1:1') or caption_style not in ('sentence','phrase','word'):
        raise ValueError('Unsupported aspect or caption style')
    voices={'kokoro':('af_heart','af_bella','am_michael','bf_emma')}
    if voice_provider not in voices or voice not in voices[voice_provider]:
        raise ValueError('Voice does not match the selected provider')
    if music not in ('ambient','none') or type(music_volume) not in (int,float) or not 0<=music_volume<=.18:
        raise ValueError('Unsupported music or volume outside 0–0.18')
    branding = {} if branding is None else branding
    if not isinstance(branding,dict) or set(branding)-{'title','footer','color','logo_asset_id'}:
        raise ValueError('Unsupported branding fields')
    brand={'title':_text(branding.get('title',''),'title',100),
           'footer':_text(branding.get('footer',''),'footer',160),
           'color':branding.get('color','#153D2D'),
           'logo_asset_id':_asset_id(branding.get('logo_asset_id'))}
    if not isinstance(brand['color'],str) or not re.fullmatch('#[0-9a-fA-F]{6}',brand['color']):
        raise ValueError('Brand color must be a six-digit hex color')
    normalized=[]
    for index,scene in enumerate(scenes,1):
        if not isinstance(scene,dict) or set(scene)-{'text','query','asset_id','duration_seconds'}:
            raise ValueError('Unsupported scene fields')
        normalized.append({'id':str(index),'text':_text(scene.get('text',''),'scene text',700,True),
            'query':_text(scene.get('query',''),'scene query',80),
            'asset_id':_asset_id(scene.get('asset_id')),'duration_seconds':scene.get('duration_seconds')})
    if sum(len(s['text']) for s in normalized)>6000:
        raise ValueError('Narration is limited to 6000 characters')
    specified=[s['duration_seconds'] is not None for s in normalized]
    if any(specified) and not all(specified):
        raise ValueError('Set every scene duration or let the planner allocate them all')
    if all(specified):
        if any(type(s['duration_seconds']) not in (int,float) or not math.isfinite(s['duration_seconds']) or s['duration_seconds']<.5 for s in normalized):
            raise ValueError('Each scene needs at least half a second')
        if abs(sum(s['duration_seconds'] for s in normalized)-duration_seconds)>.001:
            raise ValueError('Scene durations must add up to the requested duration')
    else:
        weights=[max(len(s['text'].split()),1) for s in normalized]
        for scene,weight in zip(normalized,weights):
            scene['duration_seconds']=duration_seconds*weight/sum(weights)
        if min(s['duration_seconds'] for s in normalized)<.5:
            raise ValueError('Increase duration or use fewer scenes')
    plan={'id':str(uuid4()),'duration_seconds':float(duration_seconds),'aspect':aspect,'voice':voice,
          'voice_provider':voice_provider,'music':music,'music_volume':music_volume,
          'branding':brand,'caption_style':caption_style,'scenes':normalized}
    write_json(home()/'storyboards'/f"{plan['id']}.json",plan)
    return plan


def get(plan_id):
    plan=read_json(home()/'storyboards'/f'{identifier(plan_id)}.json')
    if plan is None:raise ValueError('Unknown storyboard')
    return plan


def select(plan_id,scene_id,asset_id):
    from . import media
    plan=get(plan_id)
    chosen=_asset_id(asset_id)
    if chosen is None:raise ValueError('Select an asset identifier')
    media.asset(chosen)
    scene=next((s for s in plan['scenes'] if s['id']==scene_id),None)
    if scene is None:raise ValueError('Unknown scene')
    scene['asset_id']=chosen
    write_json(home()/'storyboards'/f'{plan["id"]}.json',plan)
    return plan


def preview(plan_id,allow_network=False):
    from PIL import Image,ImageDraw,ImageFont,ImageOps
    import imageio_ffmpeg
    from . import media
    plan=get(plan_id)
    card_w,card_h=480,350
    columns=min(len(plan['scenes']),3)
    rows=math.ceil(len(plan['scenes'])/columns)
    sheet=Image.new('RGB',(card_w*columns,card_h*rows),'#10241C')
    draw=ImageDraw.Draw(sheet)
    font=ImageFont.load_default(size=17)
    timeline=[];elapsed=0
    for index,scene in enumerate(plan['scenes']):
        x,y=(index%columns)*card_w,(index//columns)*card_h
        if scene['asset_id']:
            item=media.prepare(scene['asset_id'],allow_network=allow_network)
            if item['kind']=='image':
                with Image.open(item['path']) as source:
                    thumbnail=ImageOps.fit(source.convert('RGB'),(card_w,240))
            else:
                result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-loglevel','error',
                    '-protocol_whitelist','file,pipe','-threads','2','-i',str(item['path']),
                    '-frames:v','1','-vf',f'scale={card_w}:240:force_original_aspect_ratio=decrease,pad={card_w}:240:(ow-iw)/2:(oh-ih)/2',
                    '-f','image2pipe','-vcodec','png','-'],capture_output=True,timeout=25,check=True,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                import io
                thumbnail=Image.open(io.BytesIO(result.stdout)).convert('RGB')
            sheet.paste(thumbnail,(x,y))
        draw.text((x+12,y+248),f"Scene {scene['id']} · {elapsed:.1f}–{elapsed+scene['duration_seconds']:.1f}s",font=font,fill='#AAE8BE')
        words=scene['text'].split();line='';lines=[]
        for word in words:
            if len(line+' '+word)>47:lines.append(line);line=word
            else:line=(line+' '+word).strip()
        lines.append(line)
        draw.multiline_text((x+12,y+278),'\n'.join(lines[:3]),font=font,fill='white',spacing=3)
        timeline.append({**scene,'start':elapsed,'end':elapsed+scene['duration_seconds']})
        elapsed+=scene['duration_seconds']
    target=contained(home(),home()/'storyboards'/plan['id']/'preview.png')
    target.parent.mkdir(parents=True,exist_ok=True)
    sheet.save(target)
    return {'storyboard_id':plan['id'],'preview_path':str(target),'scenes':timeline,
            'review_required':'Check that each image or clip actually illustrates its narration.'}
