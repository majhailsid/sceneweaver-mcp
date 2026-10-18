"""One portable render worker with bounded lifetime and process-tree cancellation."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from uuid import uuid4

from .paths import home, contained, identifier, read_json, write_json

MAX_SECONDS=900
MAX_JOB_BYTES=1024**3


class WindowsJob:
    def __init__(self, process):
        import ctypes as c
        from ctypes import wintypes as w
        class Basic(c.Structure):
            _fields_=[('process_time',c.c_longlong),('job_time',c.c_longlong),('flags',w.DWORD),
                      ('minimum',c.c_size_t),('maximum',c.c_size_t),('processes',w.DWORD),
                      ('affinity',c.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class Extended(c.Structure):
            _fields_=[('basic',Basic),('io',c.c_ulonglong*6),('process_memory',c.c_size_t),
                      ('job_memory',c.c_size_t),('peak_process',c.c_size_t),('peak_job',c.c_size_t)]
        self.kernel=c.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes=[c.c_void_p,w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype=w.HANDLE
        self.kernel.SetInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
        self.kernel.CloseHandle.argtypes=[w.HANDLE]
        self.kernel.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]
        self.handle=self.kernel.CreateJobObjectW(None,None)
        limits=Extended()
        limits.basic.flags=0x2000|0x200|0x8  # Kill on close, job memory, active processes.
        limits.basic.processes=16
        limits.job_memory=4*1024**3
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(self.handle,int(process._handle)):
            self.close()
            raise OSError('Unable to assign render resource limits')

    def terminate(self):
        if self.handle:self.kernel.TerminateJobObject(self.handle,1)

    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


class JobManager:
    def __init__(self):
        self.root=home()
        self.directory=contained(self.root,self.root/'jobs')
        self.directory.mkdir(exist_ok=True)
        self._lock=threading.RLock()
        self._active=None
        self._file=contained(self.root,self.root/'server.lock').open('a+b')
        self._file.seek(0)
        if os.fstat(self._file.fileno()).st_size==0:self._file.write(b'0');self._file.flush()
        self._file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self._file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise RuntimeError('Another SceneWeaver server owns this storage directory') from None
        self._closed=False
        for folder in self.directory.iterdir():
            if folder.is_dir():
                state=read_json(folder/'status.json',{})
                if state.get('status') in ('queued','running'):
                    write_json(folder/'status.json',{'job_id':folder.name,'status':'failed','stage':'interrupted','progress':0})

    def folder(self,job_id):
        return contained(self.root,self.directory/identifier(job_id))

    def start(self,plan,allow_network=False):
        if any(not s.get('asset_id') for s in plan['scenes']):
            raise ValueError('Select an asset for every scene before rendering')
        with self._lock:
            if self._closed:raise ValueError('Server is closing')
            if self._active:raise ValueError('A render is already running')
            if len(list(self.directory.iterdir()))>=100:raise ValueError('Archive old jobs before starting more renders')
            if shutil.disk_usage(self.root).free<MAX_JOB_BYTES:raise ValueError('At least 1 GiB free storage is required')
            job_id=str(uuid4())
            folder=self.folder(job_id);folder.mkdir()
            write_json(folder/'request.json',{'plan':plan,'allow_network':allow_network is True})
            write_json(folder/'status.json',{'job_id':job_id,'status':'queued','stage':'starting','progress':0})
            allowed=('SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','LOCALAPPDATA','USERPROFILE','HOME','LANG','LC_ALL')
            env={k:os.environ[k] for k in allowed if k in os.environ}
            env.update(SCENEWEAVER_HOME=str(self.root),PYTHONUTF8='1',PYTHONNOUSERSITE='1')
            env.update(OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
            if os.environ.get('SCENEWEAVER_API_ANYTHING_MODULE'):
                env['SCENEWEAVER_API_ANYTHING_MODULE']=os.environ['SCENEWEAVER_API_ANYTHING_MODULE']
            temp=folder/'temp';temp.mkdir()
            env['TMP']=env['TEMP']=env['TMPDIR']=str(temp)
            code=f"import sys,runpy;sys.path.insert(0,{str(Path(__file__).parent.parent)!r});runpy.run_module('sceneweaver_mcp.worker',run_name='__main__')"
            options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
            process=None;resource=None
            try:
                process=subprocess.Popen([sys.executable,'-I','-c',code,job_id],stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env,**options)
                if os.name=='nt':resource=WindowsJob(process)
                self._active=(job_id,process,resource)
                process.stdin.write(b'start\n');process.stdin.close()
                threading.Thread(target=self._watch,args=(job_id,process,resource),daemon=True).start()
            except Exception:
                if process is not None:process.kill();process.wait(timeout=10)
                if resource:resource.close()
                self._active=None
                write_json(folder/'status.json',{'job_id':job_id,'status':'failed','stage':'worker_start_failed','progress':0})
                raise ValueError('Unable to start a resource-limited render worker') from None
            return {'job_id':job_id,'status':'queued','next_tool':'get_video_status'}

    def _terminate(self,process,resource):
        if resource:resource.terminate()
        elif process.poll() is None:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def _watch(self,job_id,process,resource):
        folder=self.folder(job_id);deadline=time.monotonic()+MAX_SECONDS
        reason=None
        try:
            while process.poll() is None:
                if time.monotonic()>deadline:reason='time_limit'
                total=0
                for path in folder.rglob('*'):
                    try:
                        safe=contained(self.root,path)
                        if safe.is_file():total+=safe.stat().st_size
                    except FileNotFoundError:continue
                if total>MAX_JOB_BYTES:reason='disk_limit'
                if reason:self._terminate(process,resource);break
                time.sleep(.5)
            process.wait(timeout=10)
            with self._lock:
                state=self.status(job_id)
                if state['status']=='cancelled':return
                if reason:
                    write_json(folder/'status.json',{'job_id':job_id,'status':'failed','stage':reason,'progress':0})
                elif state['status'] not in ('completed','failed'):
                    write_json(folder/'status.json',{'job_id':job_id,'status':'failed','stage':'worker_failed','progress':0})
        except Exception:
            self._terminate(process,resource)
            try:
                write_json(folder/'status.json',{'job_id':job_id,'status':'failed','stage':'watchdog_failed','progress':0})
            except OSError:pass
        finally:
            if process.poll() is None:self._terminate(process,resource)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:pass
            if resource:resource.close()
            with self._lock:self._active=None

    def status(self,job_id):
        state=read_json(self.folder(job_id)/'status.json')
        if state is None:raise ValueError('Unknown job identifier')
        return state

    def results(self,job_id):
        state=self.status(job_id)
        if state['status']!='completed':return {**state,'videos':[]}
        result=read_json(self.folder(job_id)/'results.json')
        if result is None:raise ValueError('Completed result is missing')
        for item in result.get('videos',[])+result.get('reports',[]):
            contained(self.folder(job_id),Path(item['path']))
        return result

    def cancel(self,job_id):
        with self._lock:
            state=self.status(job_id)
            if self._active and self._active[0]==job_id:
                write_json(self.folder(job_id)/'status.json',{'job_id':job_id,'status':'cancelled','stage':'cancelled','progress':0})
                self._terminate(self._active[1],self._active[2])
                return self.status(job_id)
            return state

    def close(self):
        with self._lock:
            if self._closed:return
            self._closed=True
            if self._active:self.cancel(self._active[0])
            if os.name=='nt':
                import msvcrt
                self._file.seek(0);msvcrt.locking(self._file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(),fcntl.LOCK_UN)
            self._file.close()
