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

Before sharing diagnostics, remove scripts, file paths, personal media and keys.
Do not include secrets in public GitHub issues. For sensitive vulnerabilities,
use GitHub's private vulnerability reporting if enabled; otherwise open a minimal
issue requesting a private contact without disclosing the exploit or secret.

Only the latest release is maintained. Automated dependency checks and tests are
useful checks, not evidence of compliance with a particular security standard.

