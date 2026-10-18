"""Small stdio MCP surface for a complete storyboard-to-video workflow."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any,Literal
from uuid import uuid4

from mcp.server import MCPServer
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from . import __version__, audio, media, storyboard
from .jobs import JobManager
from .paths import home,contained,identifier


def safe(operation):
    try:return operation()
    except ValueError as exc:return {'error':str(exc)[:240]}
    except Exception as exc:return {'error':f'Operation failed ({type(exc).__name__}); inspect local setup and selected media'}


def capabilities():
    import shutil
    import os
    return {'name':'SceneWeaver MCP','version':__version__,'transport':'stdio','api_keys_required':False,
        'voice':audio.capabilities(),'media_providers':list(media.PROVIDERS),
        'api_anything_configured':bool(os.environ.get('SCENEWEAVER_API_ANYTHING_MODULE')),
        'node_available':bool(shutil.which('node')),'max_duration_seconds':120,'max_scenes':30,
        'max_concurrent_jobs':1,'timeout_seconds':900,'publishing':False,
        'caption_timing':'Measured sentence timing; phrase/word timing estimated within sentences',
        'storage':str(home())}


def serve():
    manager=JobManager()
    mcp=MCPServer('SceneWeaver MCP',instructions=(
        'Use your existing assistant to write one concise narration per scene. '
        'Create a storyboard with target duration, search and review media, select an asset for every scene, '
        'preview the storyboard, then generate_video. No separate writing-model API is needed. '
        'Set allow_network only when the user authorized provider searches/downloads. '
        'Read provider notices: never retry or bypass a blocked/challenged/rate-limited source. '
        'Local Kokoro is the only voice provider; setup is explicit through the CLI. '
        'No publishing, generic shell access or arbitrary file reads are exposed.'),log_level='WARNING')
    read=ToolAnnotations(read_only_hint=True,open_world_hint=False)
    online=ToolAnnotations(read_only_hint=False,open_world_hint=True)

    @mcp.tool(annotations=read,structured_output=True)
    def get_capabilities() -> dict[str,Any]:
        """Report installed voices, provider options, limits and privacy boundaries."""
        return capabilities()

    @mcp.tool(annotations=online,structured_output=True)
    def search_media(query: str, providers: list[str]|None=None,
                     kind: Literal['mixed','image','video']='mixed',allow_network: bool=False) -> dict[str,Any]:
        """Find licensed candidates; consult source pages and notices before selecting them."""
        return safe(lambda:media.search(query,providers,kind,allow_network))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False,open_world_hint=False),structured_output=True)
    def import_media(filename: str,title: str,license_name: str='User supplied',creator: str='') -> dict[str,Any]:
        """Import only a filename staged by the operator in the managed inbox, with rights metadata."""
        return safe(lambda:media.import_asset(filename,title,license_name,creator))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False,open_world_hint=False),structured_output=True)
    def create_storyboard(scenes: list[dict],duration_seconds: float=30,
                          aspect: Literal['9:16','16:9','1:1']='9:16',voice: str='af_heart',
                          music: Literal['ambient','none']='ambient',music_volume: float=.1,
                          branding: dict|None=None,caption_style: Literal['sentence','phrase','word']='phrase') -> dict[str,Any]:
        """Plan explicit scenes: text, query, optional asset_id and optional duration_seconds.

        The assistant writes the scenes; no model API is called. Set every scene
        duration or let the planner divide the total by word count. Branding
        supports title, footer, color and a managed logo_asset_id. Shorten text
        if narration cannot fit naturally; speech is never silently cut.
        """
        return safe(lambda:storyboard.create(scenes,duration_seconds,aspect,voice,'kokoro',music,music_volume,branding,caption_style))

    @mcp.tool(annotations=read,structured_output=True)
    def get_storyboard(storyboard_id: str) -> dict[str,Any]:
        """Read a saved plan and its scene-to-media choices."""
        return safe(lambda:storyboard.get(storyboard_id))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False,open_world_hint=False),structured_output=True)
    def select_scene_asset(storyboard_id: str,scene_id: str,asset_id: str) -> dict[str,Any]:
        """Replace one scene's media choice without regenerating its script or other choices."""
        return safe(lambda:storyboard.select(storyboard_id,scene_id,asset_id))

    @mcp.tool(annotations=online,structured_output=False)
    def preview_storyboard(storyboard_id: str,allow_network: bool=False) -> CallToolResult:
        """Return a contact sheet inline and its scene timeline for semantic review."""
        result=safe(lambda:storyboard.preview(storyboard_id,allow_network))
        content=[TextContent(type='text',text=json.dumps(result))]
        if result.get('preview_path'):
            path=contained(home(),Path(result['preview_path']))
            content.append(ImageContent(type='image',data=base64.b64encode(path.read_bytes()).decode(),mime_type='image/png'))
        return CallToolResult(content=content,structured_content=result,is_error='error' in result)

    @mcp.tool(annotations=online,structured_output=True)
    def generate_video(storyboard_id: str,allow_network: bool=False) -> dict[str,Any]:
        """Start an exact-duration render of the selected storyboard; poll get_video_status."""
        return safe(lambda:manager.start(storyboard.get(storyboard_id),allow_network))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False,open_world_hint=False),structured_output=True)
    def preview_voice(text: str='Here is a short sample of this narrator.',voice: str='af_heart',speed: float=1.0) -> dict[str,Any]:
        """Create a short local WAV preview before choosing a narrator. No text leaves the computer."""
        def run():
            if not isinstance(text,str) or not 1<=len(text)<=160:raise ValueError('Preview text is limited to 160 characters')
            preview_id=str(uuid4())
            folder=contained(home(),home()/'previews'/preview_id)
            folder.mkdir(parents=True)
            result=audio.synthesize(text,voice,folder/'voice.wav',speed=speed)
            return {**result,'preview_id':preview_id,'resource_uri':f'sceneweaver://voice/{preview_id}'}
        return safe(run)

    @mcp.tool(annotations=read,structured_output=True)
    def get_video_status(job_id: str) -> dict[str,Any]:
        """Read progress and a bounded actionable failure message."""
        return safe(lambda:manager.status(job_id))

    @mcp.tool(annotations=read,structured_output=True)
    def get_video_results(job_id: str) -> dict[str,Any]:
        """Retrieve the MP4, SHA-256, credits, quality report and measured duration."""
        return safe(lambda:manager.results(job_id))

    @mcp.tool(annotations=ToolAnnotations(read_only_hint=False,destructive_hint=True,open_world_hint=False),structured_output=True)
    def cancel_video(job_id: str) -> dict[str,Any]:
        """Cancel this job and terminate its render process tree."""
        return safe(lambda:manager.cancel(job_id))

    @mcp.resource('sceneweaver://voice/{preview_id}',mime_type='audio/wav')
    def voice_resource(preview_id: str) -> bytes:
        return contained(home(),home()/'previews'/identifier(preview_id)/'voice.wav').read_bytes()

    @mcp.resource('sceneweaver://storyboard/{storyboard_id}/preview',mime_type='image/png')
    def storyboard_resource(storyboard_id: str) -> bytes:
        return contained(home(),home()/'storyboards'/identifier(storyboard_id)/'preview.png').read_bytes()

    try:mcp.run(transport='stdio')
    finally:manager.close()
