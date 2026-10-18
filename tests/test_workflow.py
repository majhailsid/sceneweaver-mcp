import asyncio
import io
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from PIL import Image
from sceneweaver_mcp import media,storyboard
from sceneweaver_mcp.jobs import JobManager
from sceneweaver_mcp import jobs
from sceneweaver_mcp.paths import contained,home,write_json


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patch=patch.dict(os.environ,{'SCENEWEAVER_HOME':self.temp.name})
        self.patch.start()

    def tearDown(self):
        self.patch.stop();self.temp.cleanup()

    def image(self):
        inbox=home()/'inbox';inbox.mkdir(exist_ok=True)
        Image.new('RGB',(1280,720),'#317543').save(inbox/'trees.png')
        return media.import_asset('trees.png','Trees fixture')

    def test_durations_and_branding_are_validated(self):
        plan=storyboard.create([{'text':'Shade cools streets.'},{'text':'Leaves release water vapor.'}],15)
        self.assertAlmostEqual(sum(s['duration_seconds'] for s in plan['scenes']),15)
        for duration in (float('nan'),float('inf'),0,121):
            with self.assertRaises(ValueError):storyboard.create([{'text':'Short.'}],duration)
        with self.assertRaises(ValueError):storyboard.create([{'text':'Short.','duration_seconds':3}],15)
        with self.assertRaises(ValueError):storyboard.create([{'text':'Short.'}],15,branding={'file':'C:/private.txt'})
        with self.assertRaises(ValueError):contained(home(),home().parent/'outside.txt')

    def test_selection_and_preview_are_managed(self):
        asset=self.image()
        plan=storyboard.create([{'text':'Trees provide shade.','query':'trees'}],15)
        selected=storyboard.select(plan['id'],'1',asset['id'])
        self.assertEqual(selected['scenes'][0]['asset_id'],asset['id'])
        result=storyboard.preview(plan['id'])
        self.assertTrue(Path(result['preview_path']).is_file())
        with self.assertRaises(ValueError):storyboard.get('../private')
        with self.assertRaises(ValueError):storyboard.select(plan['id'],'1','../private')

    def test_single_server_lock_and_unselected_scene(self):
        manager=JobManager()
        try:
            with self.assertRaises(RuntimeError):JobManager()
            with self.assertRaises(ValueError):manager.start(storyboard.create([{'text':'Short.'}],15))
        finally:manager.close()

    def test_video_preview_runs_without_a_console_window(self):
        plan=storyboard.create([{'text':'A moving scene.','asset_id':'a'*64}],3)
        png=io.BytesIO()
        Image.new('RGB',(480,240)).save(png,format='PNG')
        with patch.object(media,'prepare',return_value={'kind':'video','path':'managed.mp4'}), \
                patch.object(storyboard.subprocess,'run',return_value=Mock(stdout=png.getvalue())) as run:
            result=storyboard.preview(plan['id'])
        self.assertTrue(Path(result['preview_path']).is_file())
        self.assertEqual(run.call_args.kwargs['creationflags'],getattr(subprocess,'CREATE_NO_WINDOW',0))

    def test_worker_failure_is_visible_without_voice_models(self):
        asset=self.image()
        plan=storyboard.create([{'text':'A short narration.','asset_id':asset['id']}],3,aspect='1:1')
        manager=JobManager()
        try:
            job=manager.start(plan)
            deadline=time.monotonic()+25
            while manager._active and time.monotonic()<deadline:time.sleep(.1)
            self.assertIsNone(manager._active)
            status=manager.status(job['job_id'])
            self.assertEqual(status['status'],'failed')
            self.assertIn('Kokoro',status.get('error',''))
        finally:manager.close()

    def test_cancel_terminates_real_worker(self):
        asset=self.image()
        plan=storyboard.create([{'text':'Short narration.','asset_id':asset['id']}],3)
        manager=JobManager()
        try:
            job=manager.start(plan)
            child=manager._active[1]
            result=manager.cancel(job['job_id'])
            child.wait(timeout=10)
            self.assertEqual(result['status'],'cancelled')
            deadline=time.monotonic()+10
            while manager._active and time.monotonic()<deadline:time.sleep(.1)
            self.assertIsNone(manager._active)
        finally:manager.close()

    def test_expired_deadline_terminates_real_worker(self):
        asset=self.image()
        plan=storyboard.create([{'text':'Short narration.','asset_id':asset['id']}],3)
        manager=JobManager()
        try:
            with patch.object(jobs,'MAX_SECONDS',-1):
                job=manager.start(plan)
                deadline=time.monotonic()+15
                while manager._active and time.monotonic()<deadline:time.sleep(.1)
            self.assertIsNone(manager._active)
            self.assertEqual(manager.status(job['job_id'])['stage'],'time_limit')
        finally:manager.close()

    def test_cancel_preserves_completed_result(self):
        manager=JobManager()
        job_id=str(uuid4())
        write_json(manager.folder(job_id)/'status.json',{'job_id':job_id,'status':'completed','progress':100})
        manager._active=(job_id,Mock(),None)
        try:
            with patch.object(manager,'_terminate') as terminate:
                self.assertEqual(manager.cancel(job_id)['status'],'completed')
                terminate.assert_not_called()
        finally:
            manager._active=None
            manager.close()

    def test_cancel_waits_for_last_worker_write(self):
        manager=JobManager()
        job_id=str(uuid4())
        status_file=manager.folder(job_id)/'status.json'
        write_json(status_file,{'job_id':job_id,'status':'running'})
        process=Mock()
        process.wait.side_effect=lambda **kwargs:write_json(status_file,{'job_id':job_id,'status':'completed'})
        manager._active=(job_id,process,None)
        try:
            with patch.object(manager,'_terminate'):
                self.assertEqual(manager.cancel(job_id)['status'],'cancelled')
            process.wait.assert_called_once()
            self.assertEqual(manager.status(job_id)['status'],'cancelled')
        finally:
            manager._active=None
            manager.close()

    def test_close_waits_for_watchdog_before_unlocking_storage(self):
        manager=JobManager()
        watcher=Mock()
        watcher.is_alive.return_value=False
        def check_lock(**kwargs):
            with self.assertRaises(RuntimeError):JobManager()
        watcher.join.side_effect=check_lock
        manager._watcher=watcher
        manager.close()
        watcher.join.assert_called_once()
        replacement=JobManager()
        replacement.close()

    def test_real_stdio_storyboard_preview_and_errors(self):
        async def run():
            from mcp import Client,StdioServerParameters
            parameters=StdioServerParameters(command=sys.executable,args=['-m','sceneweaver_mcp','serve'],
                env={'SCENEWEAVER_HOME':self.temp.name,'PYTHONUTF8':'1'})
            self.image()
            async with Client(parameters) as client:
                names={t.name for t in (await client.list_tools()).tools}
                self.assertIn('preview_voice',names);self.assertIn('select_scene_asset',names)
                info=(await client.call_tool('get_capabilities',{})).structured_content
                self.assertEqual(info['name'],'SceneWeaver MCP')
                imported=(await client.call_tool('import_media',{'filename':'trees.png','title':'Trees'})).structured_content
                plan=(await client.call_tool('create_storyboard',{'scenes':[{'text':'Trees provide shade.','asset_id':imported['id']}],
                    'duration_seconds':15})).structured_content
                self.assertEqual(plan['duration_seconds'],15)
                preview=await client.call_tool('preview_storyboard',{'storyboard_id':plan['id']})
                self.assertTrue(any(item.type=='image' for item in preview.content))
                denied=(await client.call_tool('import_media',{'filename':'../private.txt','title':'bad'})).structured_content
                self.assertIn('error',denied)
                invalid=(await client.call_tool('generate_video',{'storyboard_id':'../private'})).structured_content
                self.assertIn('error',invalid)
        asyncio.run(run())


if __name__=='__main__':unittest.main()
