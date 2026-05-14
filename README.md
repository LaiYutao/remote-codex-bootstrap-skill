# Remote Codex Bootstrap Skill

A Codex skill for turning a fresh root Ubuntu/Debian SSH host into a Codex App remote development target.

This repository is meant to be installed as a **Codex skill**. The bundled Python script is an implementation detail that the skill runs after you give Codex an SSH command and temporary password.

## Install

Clone this repository into your Codex skills directory:

```bash
mkdir -p "$CODEX_HOME/skills"
git clone https://github.com/LaiYutao/remote-codex-bootstrap-skill.git \
  "$CODEX_HOME/skills/remote-codex-bootstrap"
```

If `CODEX_HOME` is not set, Codex commonly uses `~/.codex`:

```bash
git clone https://github.com/LaiYutao/remote-codex-bootstrap-skill.git \
  ~/.codex/skills/remote-codex-bootstrap
```

Restart Codex if needed so it reloads available skills.

## Use

Set your provider configuration in `~/.env` or in the environment where Codex runs:

```bash
CODEX_REMOTE_CC_PROVIDER_NAME=custom
CODEX_REMOTE_CC_BASE_URL=https://api.openai.com/v1
CODEX_REMOTE_CC_MODEL=gpt-5.5
CODEX_REMOTE_CC_API_KEY=...
```

Then ask Codex to use the skill with your remote SSH command and temporary password, for example:

```text
[$remote-codex-bootstrap] ssh -p 35842 root@connect.example.com <temporary-password> 配置一下
```

Codex will run the skill workflow for you. It should configure reusable SSH key access, install remote tools, install Codex, configure the default provider, and report the Codex App connection target.

## Provider Configuration

The skill does not hardcode provider name, base URL, model, or API key. It reads them from:

- `CODEX_REMOTE_CC_PROVIDER_NAME`
- `CODEX_REMOTE_CC_BASE_URL`
- `CODEX_REMOTE_CC_MODEL`
- `CODEX_REMOTE_CC_API_KEY`

You can also pass `--cc-provider-name`, `--cc-base-url`, or `--cc-model` as one-off overrides, but environment variables are preferred for durable defaults.

## Scope

This skill is intentionally scoped to root Ubuntu/Debian-style remote hosts. It is designed for fresh disposable remote development machines where Codex can install packages as `root`.

If bubblewrap namespace creation is blocked by the provider outer container, the workflow reports that Codex sandboxing is unavailable and continues the remaining setup.

## cc-switch Download Recovery

If remote GitHub release downloads fail, the skill tells the agent to recover by downloading the release asset locally, copying it to the remote, and rerunning the bootstrap with:

```bash
--skip-minimal-cli --cc-switch-archive /tmp/cc-switch-cli-linux-x64.tar.gz
```

This recovery path lets the remaining provider setup and final checks continue smoothly.
