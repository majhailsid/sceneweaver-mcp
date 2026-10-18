"""Fixed render entry point, released only after parent resource limits attach."""
from pathlib import Path
import hashlib
import os
import sys

from .paths import home,contained,identifier,read_json,write_json


def main():
    if sys.stdin.readline().strip()!='start':return 2
    job_id=identifier(sys.argv[-1])
    folder=contained(home(),home()/'jobs'/job_id)
    request=read_json(folder/'request.json')
    if os.name!='nt':
        import resource
        resource.setrlimit(resource.RLIMIT_CPU,(900,900))
        # macOS does not consistently support RLIMIT_AS; report limits honestly.
        if sys.platform!='darwin':resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,4*1024**3))
    def progress(stage,scene_index=0):
        value=5+85*scene_index/max(len(request['plan']['scenes']),1)
        write_json(folder/'status.json',{'job_id':job_id,'status':'running','progress':max(0,min(99,int(value))),
                                       'stage':str(stage)[:48]})
    try:
        from .render import render_storyboard
        progress('starting')
        result=render_storyboard(request['plan'],folder,progress,allow_network=request['allow_network'])
        video=contained(folder,Path(result['video']))
        if video.suffix!='.mp4' or not video.is_file():raise ValueError('Renderer produced no video')
        write_json(folder/'credits.json',result.get('credits',[]))
        write_json(folder/'quality.json',result.get('report',{}))
        with video.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        payload={'job_id':job_id,'videos':[{'name':video.name,'path':str(video),'mime_type':'video/mp4',
            'bytes':video.stat().st_size,'sha256':digest}],
            'reports':[{'name':name,'path':str(folder/name),'mime_type':'application/json'} for name in ('credits.json','quality.json')],
            'duration_seconds':result['duration_seconds'],'resolution':result['resolution']}
        write_json(folder/'results.json',payload)
        write_json(folder/'status.json',{'job_id':job_id,'status':'completed','progress':100,'stage':'complete'})
        return 0
    except Exception as exc:
        message=str(exc)[:240] if isinstance(exc,ValueError) else f'Render failed ({type(exc).__name__})'
        write_json(folder/'status.json',{'job_id':job_id,'status':'failed','progress':0,'stage':'render_failed','error':message})
        return 1


if __name__=='__main__':raise SystemExit(main())
