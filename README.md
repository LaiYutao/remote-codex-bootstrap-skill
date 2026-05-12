# Remote Codex Bootstrap

A Codex skill for turning a fresh root Ubuntu/Debian SSH host into a Codex App remote development target.

It configures reusable SSH key access, enables Codex remote connections locally, installs baseline CLI tools, installs remote Codex, verifies bubblewrap sandbox support, and configures a default Codex model provider from environment variables.

## Quick Start

Set your provider API key locally:

```bash
export CODEX_REMOTE_CC_API_KEY=...
```

Run the bootstrap script:

```bash
python3 scripts/bootstrap_remote_codex.py \
  --ssh-command 'ssh -p 35842 root@connect.example.com' \
  --password '<temporary password>' \
  --create-workspace
```

Override provider defaults when needed:

```bash
python3 scripts/bootstrap_remote_codex.py \
  --ssh-command 'ssh -p 35842 root@connect.example.com' \
  --password '<temporary password>' \
  --cc-provider-name custom \
  --cc-base-url https://api.openai.com/v1 \
  --cc-model gpt-5.5 \
  --create-workspace
```

## Scope

This skill is intentionally scoped to root Ubuntu/Debian-style remote hosts. It may refuse or fail on non-root hosts or providers that block required package installation.

If bubblewrap namespace creation is blocked by the provider outer container, the script reports that Codex sandboxing is unavailable and continues the remaining setup.

## cc-switch Download Recovery

If remote GitHub release downloads fail, the agent can download the release asset locally, copy it to the remote, then rerun with:

```bash
--skip-minimal-cli --cc-switch-archive /tmp/cc-switch-cli-linux-x64.tar.gz
```
