# Client detection and connection

The included installer runs `sceneweaver-mcp connect` after installing packages.
This checks known configuration folders, lists detected clients, and asks which
one to connect. Enter skips the change. An unattended install skips registration.
Installing the wheel with pip or starting the MCP server never changes client
settings. Registration is not exposed to an agent as an MCP tool.

## Commands

```sh
sceneweaver-mcp clients
sceneweaver-mcp connect
sceneweaver-mcp connect --client cursor --dry-run
sceneweaver-mcp connect --client cursor
```

Use the executable from the installed environment. `clients` only reports paths
and whether configuration folders exist. `--dry-run` reports the proposed
SceneWeaver entry without printing other settings or creating files. Explicit
`--client` selects and authorizes that one write, even if its folder is absent.
The entry points to this environment's absolute Python executable, with arguments
`-m sceneweaver_mcp serve`. Keep the environment in place after connecting.

## Supported locations

| Client ID | Location | Platforms |
| --- | --- | --- |
| `codex` | `$CODEX_HOME/config.toml`, or `~/.codex/config.toml` | Windows, macOS, Linux |
| `cursor` | `~/.cursor/mcp.json` | Windows, macOS, Linux |
| `claude-desktop` | `%APPDATA%/Claude/claude_desktop_config.json` | Windows |
| `claude-desktop` | `~/Library/Application Support/Claude/claude_desktop_config.json` | macOS |

These paths follow the documented [shared MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[Cursor configuration](https://prod.cursor.com/help/customization/mcp), and
[Claude Desktop local-server setup](https://modelcontextprotocol.io/docs/develop/connect-local-servers).
An existing folder is a detection hint, not proof the app is installed or running.
Other clients, custom profiles, portable installs, Linux Claude wrappers, JSONC
files, and unsupported TOML layouts require manual setup using `examples/mcp.json`
and the client's own configuration format. Enterprise policies may prevent a
registered server from becoming available.

## What changes

Close the selected client before connecting. SceneWeaver adds just its server
entry. Other servers and settings are preserved; TOML comments are preserved.
JSON formatting may change. A different existing `sceneweaver` entry is never
overwritten: edit or remove it in the client before connecting a new environment.
An identical entry is left alone and creates no additional backup.

Existing configuration is backed up beside the original as
`FILENAME.sceneweaver-backup-UNIQUE_ID`. The command reports its path. Backup files
can contain existing credentials; keep them private. Windows uses a replacement
operation that preserves the original access controls. POSIX backups are created
with owner-only permissions. Invalid, linked, duplicate-key, oversized, or changing
configurations are rejected. The tool does not relax sandbox rules or tool trust,
start/restart applications, install itself as a background service, or enable
automatic tool approval.

Restart the client and approve the server using the client's controls. Local
voice still needs `sceneweaver-mcp setup-voice` once. Only one MCP process can own
each SceneWeaver storage directory; use one connected client at a time, or give
each client a separate `SCENEWEAVER_HOME` in its server environment settings.

To disconnect, remove only the `sceneweaver` server entry using your client's
settings. A backup can restore the old file if nothing else has changed since;
otherwise restore only the relevant entry so newer settings are preserved.
