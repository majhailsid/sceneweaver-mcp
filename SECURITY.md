# Security

SceneWeaver is a local stdio MCP server. Give it the same trust as any program
running under your account. It is not an operating-system sandbox or a certified
security product. Do not expose it as a public network service.

Use a current supported Python version, install packages from a trusted release,
and keep FFmpeg and image libraries updated. Downloaded media is untrusted input:
file-type, URL and size validation reduce risk but cannot eliminate parser bugs.
API-Anything and local voice services are separate processes with their own trust
boundaries. Do not point an integration at an untrusted executable or service.

Provider requests disclose the search query and your public IP to that provider.
Local Kokoro narration stays local after its explicit initial model download.
No key for an LLM provider is required: your connected assistant supplies the text.
An MCP client may still retain prompts and tool results under its own policies.
Job state, cached media and output files persist on your computer until removed.

Client discovery is local and read-only. Registration is a separate CLI action,
offered by the installer only after the operator selects a client. It is never
performed by package installation, server startup, or an MCP tool call. It adds
only the SceneWeaver entry, preserves other settings, and backs up existing files.
Windows replacement preserves file access controls; POSIX backups are private.
Linked paths, malformed settings, duplicate JSON keys, conflicting entries, and
oversized files are refused. Close the selected client before making changes;
an editor can otherwise race any local configuration writer. Backups may contain
credentials from the original client configuration: keep them private, never
commit them, and remove them when no longer needed. Restart and trust decisions
remain under the client's control.

Before sharing diagnostics, remove scripts, file paths, personal media and keys.
Do not include secrets in public GitHub issues. For sensitive vulnerabilities,
use GitHub's private vulnerability reporting if enabled; otherwise open a minimal
issue requesting a private contact without disclosing the exploit or secret.

Only the latest release is maintained. Automated dependency checks and tests are
useful checks, not evidence of compliance with a particular security standard.

