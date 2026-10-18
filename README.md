# SceneWeaver MCP

A local MCP connector that turns an assistant's script into a narrated short
video. Plan scenes, inspect a storyboard, choose media, preview a voice, then
render to a requested duration. No LLM API key is required: your existing
assistant supplies the narration and search terms.

SceneWeaver is an early release. Review the storyboard and asset credits before
publishing a video. Visual relevance still benefits from a human's judgment.

## Install locally

Requires Python 3.11 or newer and a supported 64-bit platform. Python 3.11 or 3.12
is recommended for the optional voice engine's native dependencies. Installation
downloads Python packages; voice models are a separate explicit download.

Download and extract a release bundle from
[GitHub Releases](https://github.com/majhailsid/sceneweaver-mcp/releases), then
install its wheel in a virtual environment:

The bundle also contains `examples/install-windows.cmd` and
`examples/install-posix.sh`. Run the matching installer from a terminal to create
a local environment and install the voice extra. Then run `setup-voice` explicitly
as shown below. These scripts download packages; they do not download voice models.

```powershell
# Windows PowerShell, from the extracted bundle directory
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install "./sceneweaver_mcp-0.1.0-py3-none-any.whl[voice]"
.\.venv\Scripts\sceneweaver-mcp setup-voice
.\.venv\Scripts\sceneweaver-mcp doctor
```

```sh
# macOS / Linux, from the extracted bundle directory
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install './sceneweaver_mcp-0.1.0-py3-none-any.whl[voice]'
.venv/bin/sceneweaver-mcp setup-voice
.venv/bin/sceneweaver-mcp doctor
```

For a source checkout, replace the wheel path with `'.[voice]'`. With uv, run
`uv sync --extra voice`, then `uv run sceneweaver-mcp setup-voice`. The voice
extra installs Kokoro ONNX and its speech dependencies; `setup-voice` downloads
approximately 355 MB of integrity-checked model and voice files. It never runs
silently when the MCP server starts. Installing the core without `[voice]` still
provides planning and media tools; local narration requires the extra and models.

FFmpeg is supplied through imageio-ffmpeg on supported platforms. Its executable
and codec licensing are separate from this project's Apache license. See
[third-party notices](THIRD_PARTY_NOTICES.md) before redistributing an environment.

## Connect an MCP client

Use the absolute executable path from the environment you just installed. The
server uses stdio and needs no localhost port. A generic client configuration is
in [examples/mcp.json](examples/mcp.json); adapt it to your client's schema.

```json
{
  "mcpServers": {
    "sceneweaver": {
      "command": "/absolute/path/to/.venv/bin/sceneweaver-mcp",
      "args": ["serve"]
    }
  }
}
```

On Windows, use `C:\\absolute\\path\\.venv\\Scripts\\sceneweaver-mcp.exe`.
Run `sceneweaver-mcp version` to confirm the executable. Set `SCENEWEAVER_HOME`
in the MCP process environment if you want to choose where state, media and
results are stored; `doctor` reports the active location.

The optional launchers are `examples/run-windows.cmd` and
`examples/run-posix.sh`. If your client needs an interpreter to launch a script,
use `cmd /d /c` on Windows or `sh` on POSIX, with the absolute script path as
arguments. The installed `sceneweaver-mcp` executable above is the simplest
configuration. POSIX launchers can also be run as `sh examples/run-posix.sh` if
executable permission was not preserved by ZIP extraction.

## Make a video

Ask your connected assistant:

> Make a 15-second video explaining how trees cool cities. Plan three scenes,
> find relevant footage from the available providers, and show the storyboard.
> Preview the narrator before rendering. Use quiet background music, concise
> captions and the selected scenes. Give me the video and its asset credits.

The workflow is: plan scenes → search and select media → review storyboard →
preview narration → generate → check progress → retrieve results. You can replace
a scene's selection before rendering and cancel an active job. Cached downloads
reduce repeat requests, while provider cooldowns avoid repeatedly hitting a
limited service. Uploaded/imported media must be yours to use.

The renderer fits measured narration to the requested duration within its allowed
speed range; it fails with a useful message when the script needs rewriting
rather than forcing an unnatural voice speed. Caption timing uses measured
sentence boundaries. Phrase and word highlighting use estimated timing inside
those sentences, rather than speech-recognition word alignment.

Branding supports a title, footer, six-digit hex color and an imported logo asset ID.

| Tool | Purpose |
| --- | --- |
| `get_capabilities` | Inspect providers, narration and setup status. |
| `search_media`, `import_media` | Discover licensed media or register managed local assets. |
| `create_storyboard`, `get_storyboard` | Save and inspect assistant-written scene text and timing. |
| `select_scene_asset`, `preview_storyboard` | Change a scene's asset and inspect a thumbnail contact sheet. |
| `preview_voice` | Hear the selected narrator before a full render. |
| `generate_video` | Render the selected storyboard to its requested duration. |
| `get_video_status`, `get_video_results`, `cancel_video` | Track a job, retrieve outputs or cancel. |

`create_storyboard` accepts `scenes` containing `text`, `query`, an optional
`asset_id` and optional `duration_seconds`. Set durations for every scene or let
the planner allocate them by word count. Set the total `duration_seconds`
(1–120), `aspect` (`9:16`, `16:9` or `1:1`), `voice`, `music` (`ambient` or
`none`), `music_volume` (0–0.18), `branding` and `caption_style`
(`sentence`, `phrase` or `word`). Available Kokoro voices are `af_heart`,
`af_bella`, `am_michael` and `bf_emma`.

To import media, place a file in the managed `inbox/` under the storage directory
reported by `doctor`, then call `import_media` with its filename and rights
metadata. Tools cannot import an arbitrary absolute path. Provider searches and
downloads require `allow_network=true`; choose it only with the user's permission.

Voice previews return a WAV path and `sceneweaver://voice/{preview_id}` resource.
Storyboard previews include an inline PNG contact sheet and can also be read from
`sceneweaver://storyboard/{storyboard_id}/preview`. Playback and resource display
depend on the connected MCP client's capabilities. Video results include the
local MP4 path, its checksum, credits and a quality report.

## Providers and integrations

Wikimedia Commons and Openverse provide image discovery; Pexels provides stock
video discovery through the optional API-Anything bridge. Individual providers
can be unavailable or rate-limited. Media credits travel with the job. A free
website does not automatically grant permission for any use of its content.

Kokoro runs locally without an API key after setup. The generated ambient music
bed contains no external song recording. Additional local voice service options
are documented as research; an API-Anything speech connector is not included in
this release.

See [integration setup and provider options](docs/integrations.md),
[privacy and security](SECURITY.md), and [licensing](THIRD_PARTY_NOTICES.md).

## Develop and package

```sh
python -m pip install -e '.[dev,voice]'
python -m unittest discover -s tests -v
python scripts/package_release.py
python -m pip_audit
```

The release script builds a wheel, source distribution, downloadable ZIP bundle
and SHA-256 checksums in `dist/`. It packages code and documentation, never local
jobs, cached downloads, voice models or credentials. Builds install dependencies
from package indexes; the bundle is not an offline all-dependencies installer.
CI covers Windows, macOS and Linux; a configured workflow is not a claim that
remote CI has already passed for an unpublished commit.

Release verification on Windows: the local test suite passed, an actual stdio MCP
job rendered an exact 15-second video with local Kokoro narration, and an actual
API-Anything Commons search returned six assets. macOS/Linux checks are configured
in CI but have not yet been executed for this release. These checks do not certify
all provider availability, narration pronunciations or asset rights.

## License

Original code: [Apache-2.0](LICENSE), copyright SceneWeaver contributors.
External components and downloaded assets keep their own licenses and required
attributions. SceneWeaver is not endorsed by its media or voice providers.

