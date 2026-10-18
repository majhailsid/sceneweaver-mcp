# Integrations and provider choices

## Optional API-Anything catalog bridge

Commons and Openverse use documented APIs directly by default. To route their
catalog requests through API-Anything, or enable public Pexels video discovery,
install the external project separately. Requires Node.js 22.13 or newer and npm:

```sh
git clone https://github.com/goodnight000/api-anything.git
cd api-anything
git checkout b20d809d218a1273c1941b72a8cd8188e11da7cc
npm ci
npm run build
```

Set `SCENEWEAVER_API_ANYTHING_MODULE` in your MCP client's environment to the
absolute path of that checkout's `dist/index.js`. Restart the MCP connection.
The reviewed revision is pinned for reproducibility; inspect updates before
changing it. The Python package includes only SceneWeaver's small operation
bridge, not API-Anything's repository, Node runtime or dependencies.

The bridge permits fixed catalog operations. It does not expose arbitrary URLs,
website writes, account sessions or browser challenge bypass to MCP callers.
Configured bridge failures are reported; the tool does not silently change
transport. If Pexels blocks a public search, choose another provider or import
licensed footage instead of repeatedly retrying it.

## Available media

| Source | Credential requirement | Reuse considerations |
| --- | --- | --- |
| Wikimedia Commons | No key for normal public discovery | Per-file licenses; this connector filters to supported public-domain, CC0 and CC BY results and retains attribution metadata. |
| Openverse | Public access is available with lower limits | Discovery index, not a rights owner; the connector limits results to supported licenses and approved hosts. |
| Pexels public catalog through API-Anything | No key; may be unavailable | Pexels License applies. Public page extraction can break or be blocked. |
| Managed local library | No provider | Import only media you are entitled to use; keep your source and license description. |

Commons and Openverse can expose images; a rendered still with a pan or zoom is
still an image, not newly filmed footage. Review scene selections to avoid a
slideshow when your subject needs real motion. Source metadata is useful evidence,
not a guarantee about uploader rights or recognizable people/property.

Primary references: [Commons image metadata](https://www.mediawiki.org/wiki/API:Imageinfo),
[Openverse API](https://api.openverse.org/v1/),
[Openverse authentication and throttling](https://docs.openverse.org/api/reference/authentication_and_throttling.html),
[Pexels License](https://www.pexels.com/license/),
[API-Anything](https://github.com/goodnight000/api-anything).

## Voice and music

The built-in narration path is local Kokoro ONNX after an explicit model setup.
Preview voices before rendering; accent, pronunciation and pacing vary by script.
The ambient background is generated locally and kept below narration. The package
does not download commercial music or claim a voice service subscription is free.

The following additional options were researched, not bundled or enabled merely
by appearing in this table:

| Option | Why consider it | Requirement or limitation |
| --- | --- | --- |
| [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) | Local HTTP speech service, voice mixing and timestamps | Separate service and model setup. Apache-2.0 wrapper with component notices. Not a drop-in promise that every endpoint is exposed by SceneWeaver. |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) | Small local speech models | Current engine is GPL-3.0; voice model licenses vary. Needs a deliberate integration and distribution review. |
| [Pexels official API](https://www.pexels.com/api/documentation/) | Stable supported stock video API | Requires a provider API key. Better for regular production use if keys become acceptable. |
| [Pixabay API](https://pixabay.com/api/docs/) | Additional stock image/video discovery | Requires an API key and compliance with its caching, display and Content License rules. |
| [NASA Image and Video Library](https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf) | Public science/space media discovery | No key is shown for this API's search endpoint. Review per-item third-party rights and NASA's branding restrictions; not a general-purpose local business footage source. |

NASA rights reference: [NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/).
Provider availability and terms can change; checked 2026-10-18. Prefer documented
public APIs over brittle webpage extraction when they meet your requirements.

