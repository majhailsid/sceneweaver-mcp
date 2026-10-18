# Third-party notices

The Apache-2.0 license applies to original SceneWeaver code. Installing a dependency
does not relicense that dependency. Python packages retain their license files in
their installed distributions; consult those files before redistributing a bundled
environment. The release contains source and Python package artifacts, not an
embedded Python installation, Node installation, voice model or media collection.

## Runtime dependencies

| Component | Upstream | License or notice |
| --- | --- | --- |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | MIT |
| Pillow | https://python-pillow.github.io/ | HPND and included third-party notices |
| NumPy | https://numpy.org/ | BSD-3-Clause and included notices |
| Requests | https://requests.readthedocs.io/ | Apache-2.0 |
| imageio-ffmpeg | https://github.com/imageio/imageio-ffmpeg | BSD-2-Clause; bundled FFmpeg executable has separate licensing |
| FFmpeg | https://ffmpeg.org/legal.html | Build-specific LGPL/GPL terms; inspect the installed executable's configuration and license |

The original SceneWeaver renderer uses FFmpeg directly. No external video engine
source tree is bundled in this release.

## Optional voice and website integrations

- [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) is MIT-licensed.
  Its dependencies have their own licenses, including GPL-licensed speech tooling
  where applicable. Keep those notices if redistributing an installed environment.
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model weights are
  Apache-2.0. Models and voice files are downloaded separately with `setup-voice`;
  they are not covered by the SceneWeaver code license merely because they are used.
- [API-Anything](https://github.com/goodnight000/api-anything) is an optional external
  MIT-licensed program. Copyright (c) 2026 Tianjun Zheng. Its source and dependencies
  are not bundled. SceneWeaver's integration bridge is original code. If you
  redistribute API-Anything, retain its full MIT license and copyright notice.
- [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) is an optional separate
  Apache-2.0 service; it has additional component notices and model requirements.

## Downloaded media

Pexels uses the [Pexels License](https://www.pexels.com/license/), not Apache-2.0.
Openverse indexes material under individual Creative Commons and public-domain
terms; it does not own every result. Wikimedia Commons also assigns licenses per
file. Verify source, creator, license, attribution and any model/property rights
before publication. SceneWeaver records available provenance with downloaded media
and render results. A search result is not a warranty that reuse is permitted.

Synthetic ambient music produced by the original SceneWeaver generator contains
no sampled third-party recording. This statement does not cover a music file you
import yourself. You remain responsible for imported assets.

