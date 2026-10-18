# Optional API-Anything transport

API-Anything is an external MIT-licensed project by goodnight000:
https://github.com/goodnight000/api-anything

SceneWeaver does not bundle it or change its license. Install the reviewed revision
`b20d809d218a1273c1941b72a8cd8188e11da7cc` separately with Node.js 22.13+:

```sh
git clone https://github.com/goodnight000/api-anything.git
cd api-anything
git checkout b20d809d218a1273c1941b72a8cd8188e11da7cc
npm ci
npm run build
```

Set `SCENEWEAVER_API_ANYTHING_MODULE` in your MCP client's environment to the absolute
path of that installation's `dist/index.js`. This is operator configuration; tools
cannot set it. The bridge executes only three fixed read-only operations, with
public DNS pinning, no cookies, browser escalation, writes, or challenge bypass.
API-Anything stores its generated site specs under SceneWeaver's managed data folder.
If explicitly configured and broken, search reports failure rather than silently
switching transports. Without it, Commons and Openverse use their documented APIs;
the returned notices identify that transport. Pexels requires the optional bridge.
Public Pexels page extraction is fragile and may be blocked: use another provider
or import licensed clips from the managed inbox rather than repeatedly retrying.

Primary catalog documentation:
- https://www.mediawiki.org/wiki/API:Imageinfo
- https://api.openverse.org/v1/

Openverse is restricted to Flickr files on approved media hosts, CC0/public domain
and CC BY. Commons also excludes NC, ND and SA assets and reported restrictions.
Attribution is retained; catalog labels cannot guarantee every uploader has rights.
Other reviewed choices: NASA Images API (https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf)
is useful for space topics, but per-item third-party rights need review; it is not
enabled. Pexels' official API (https://www.pexels.com/api/documentation/) is more stable
than public HTML but requires a key, so it is not the default key-free transport.
