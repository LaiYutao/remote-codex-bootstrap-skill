---
name: remote-codex-bootstrap
description: "Use when the user wants to turn a fresh SSH-accessible remote Linux machine into a Codex App remote development host. Trigger whenever the user provides or mentions an SSH command, host, port, login user, or temporary password and asks to configure/bootstrap/connect a remote machine for Codex App, VS Code Remote-SSH, cc-switch, or remote development. Default behavior: run the bundled bootstrap script, configure reusable SSH key access, install minimal Ubuntu CLI tools, install remote Codex when missing, configure the user's default cc-switch/Codex provider, and report the Codex App connection target."
---

# Remote Codex Bootstrap

## When Triggered

Do not merely explain the process. If the user gives an SSH command and password, run the bundled script unless they explicitly ask for a plan or explanation only.

The user normally provides:

- SSH command, for example `ssh -p 35842 root@connect.example.com`
- temporary SSH password
- optional alias or remote workspace path

Assume root Ubuntu/Debian-style remote hosts unless the command says otherwise. If the host is non-root or not apt-based, stop before system package changes and explain what is unsupported.

## Default Command Shape

Use this script:

```bash
python3 $CODEX_HOME/skills/remote-codex-bootstrap/scripts/bootstrap_remote_codex.py \
  --ssh-command '<ssh command>' \
  --password '<temporary password>' \
  --create-workspace
```

If the password is available from the user's message in the current turn, pass it with `--password '<temporary password>'` so the script does not fall back to interactive `getpass`, which may fail or echo in non-TTY Codex runs. If avoiding argv exposure is preferred, set a short-lived environment variable and pass `--password-from-env <VAR>` instead.

Defaults:

- reusable key: `~/.ssh/id_ed25519_codex`
- SSH alias: include the SSH port so repeated provider hosts remain distinguishable; for SeetaCloud-style `connect.*.seetacloud.com` hosts, default to `seetacloud-<port>` unless the user provides `--alias`
- provider name env var: `CODEX_REMOTE_CC_PROVIDER_NAME`
- base URL env var: `CODEX_REMOTE_CC_BASE_URL`
- model env var: `CODEX_REMOTE_CC_MODEL`
- API key env var: `CODEX_REMOTE_CC_API_KEY`
- root workspace: `/root/workspace`
- remote Codex profile: default to syncing a filtered version of local `~/.codex/AGENTS.md` to remote `~/.codex/AGENTS.md`, and generate remote-safe `~/.codex/config.toml` features plus `~/.codex/rules/default.rules`. Strip local-only dependency, GitHub/network, and email environment sections; do not copy secrets, sessions, automations, plugin caches, skills, memories, or other local state.
- download/network behavior: default to direct network with proxy variables unset; do not source `/etc/network_turbo` for npm/Codex installs. For GitHub release downloads, the script tries direct remote download first with a short timeout, then `/etc/network_turbo`; if both fail, the agent should take over with local `gh api` download plus `scp`, then rerun the bootstrap with `--skip-minimal-cli --cc-switch-archive /tmp/cc-switch-cli-linux-x64.tar.gz` so provider setup and final checks continue smoothly. Always unset proxy variables afterward.

If any provider variable is missing, ask the user to set it in `~/.env` or in the current environment. Do not silently skip provider setup, because provider setup is part of the default success criteria.

Useful escape hatches:

- `--alias <name>` when the user requests a specific SSH alias.
- `--workspace-root <path>` when the user gives a project/workspace path.
- `--password <temporary password>` when the user provided the password in the prompt and the current run can pass it directly; do not include passwords in final responses.
- `--password-from-env <VAR>` only for a short-lived password variable.
- `--skip-minimal-cli` if apt mirrors are broken or when rerunning after the baseline CLI tools already installed.
- `--cc-switch-archive <remote tar.gz>` after the agent has copied a cc-switch release tarball to the remote; the script installs from that archive and continues provider setup.
- `--cc-provider-name`, `--cc-base-url`, and `--cc-model` only for one-off overrides; prefer `~/.env` for durable defaults.
- `--skip-remote` only for local config dry-runs.

## What The Script Does

1. Parse the SSH command into user, host, and port.
2. Create or reuse `~/.ssh/id_ed25519_codex`; never overwrite an existing private key.
3. Add/update one `Host <alias>` block in local `~/.ssh/config`; use a port-bearing default alias, such as `seetacloud-49704`, for remote providers that reuse hostnames across many machines.
4. Ensure local `~/.codex/config.toml` has `[features] remote_connections = true`.
5. Use the temporary password once to append the public key to remote `~/.ssh/authorized_keys`, then verify passwordless SSH.
6. Write default `/root/.bash_aliases` conveniences:
   - Ghostty TERM fallback to `xterm-256color`
   - `ll`, `la`, `l`
   - `tb` for `/etc/network_turbo`
   - `us` to unset HTTP/HTTPS proxy variables
   - `batcat -> bat`, `fdfind -> fd`, `zoxide init bash`
7. Install minimal root Ubuntu/Debian CLI tools: terminal fixes, Git, curl/wget/gnupg, Python basics, `rg`, `fd-find`, `fzf`, `jq`, `bat`, `tree`, `tmux`, `zoxide`, `bubblewrap`/`bwrap` for Codex sandboxing, archive/process/network basics, `vim`, and `nano`.
8. Verify that `bubblewrap` sandboxing actually works, not only that `bwrap` exists on `PATH`; run a smoke test that creates a minimal namespace and prints `bwrap-ok`.
   - If `bwrap` is missing, install `bubblewrap`.
   - If the smoke test fails with `Operation not permitted`, report briefly that the remote is limited by the provider's outer container and Codex sandboxing is unavailable; do not include low-level namespace/capability diagnostics unless the user explicitly asks.
   - Do not treat a mere `command -v bwrap` success as sufficient.
9. Install remote Codex if missing:
   - install Node.js LTS through NodeSource if `npm` is missing
   - unset `http_proxy`, `https_proxy`, `HTTP_PROXY`, and `HTTPS_PROXY` before npm
   - run `npm install -g @openai/codex` without `/etc/network_turbo` by default
10. Check/install `cc-switch` and write remote Codex default provider config using `CODEX_REMOTE_CC_API_KEY`:
   - first try the already installed `cc-switch`
   - then try direct GitHub release tarball download
   - only if direct GitHub download fails, retry the tarball with `/etc/network_turbo`
   - if both remote download paths fail or time out, exit with a clear recovery message; the agent downloads the exact release asset locally through `gh api`, copies it to the remote with `scp`, then reruns with `--cc-switch-archive` to continue from the archive
   - avoid relying solely on `latest/download/install.sh`, because some remote providers return 503 for that endpoint
11. Generate the remote Codex profile:
   - sync local `~/.codex/AGENTS.md` to remote `~/.codex/AGENTS.md` when it exists, filtering local-only sections instead of copying it verbatim
   - strip local-only sections such as `Environment Dependency Policy`, `GitHub CLI / Network Policy`, and `Codex Automation Email Environment`
   - extend remote `~/.codex/config.toml` with safe feature and memory toggles while preserving provider setup
   - write remote `~/.codex/rules/default.rules` with only narrow remote-safe allow rules for `gh api`, `gh repo fork`, `gh run view`, `gh gist`, and `git add`
   - do not copy `auth.json`, sessions, logs, automations, plugin caches, skills, memories, or other local state
12. Verify and print the Codex App target host alias and suggested remote directory.

## Safety And Failure Rules

- Keep SSH passwords and API keys out of final responses.
- Do not store SSH passwords in files, skill files, or memory.
- Do not hardcode API keys in the skill. Use `CODEX_REMOTE_CC_API_KEY`.
- Avoid interactive password prompts in Codex runs. When a password was provided, pass it via `--password` or `--password-from-env`; only use `getpass` when no password was supplied.
- Do not install Ubuntu's `npm` package; use NodeSource `nodejs`.
- If apt, NodeSource, npm, GitHub releases, or cc-switch downloads fail, report the failing stage and suggest the smallest resumable command or flag. Suggest `--skip-minimal-cli` only when apt package setup is the blocker.
- If bubblewrap sandbox smoke testing fails, report the provider outer-container limitation briefly, continue installing Codex and provider config, and do not call the remote fully ready for Codex sandboxed work. Installing `bubblewrap` alone is not enough.
- Default to direct network access. Do not source `/etc/network_turbo` globally. Use it only as a fallback around GitHub release downloads, then unset `http_proxy`, `https_proxy`, `HTTP_PROXY`, and `HTTPS_PROXY`. Prefer a 60-second remote download timeout before handing recovery back to the agent; two minutes is usually too long for provider-side 503 or stalled GitHub release downloads. After agent-side recovery, rerun the same SSH target with `--skip-minimal-cli --cc-switch-archive /tmp/cc-switch-cli-linux-x64.tar.gz`.
- Avoid sending complex semicolon-heavy remote commands through an interpolated `expect` string. Write the expect program to a temporary file and pass SSH argv to that file's `$argv`; some local `expect -c` builds do not populate `$argv` and instead treat later arguments as script filenames. Keep shell metacharacters interpreted only on the remote host.
- After claiming that a public key was installed, verify that the exact public key is present in remote `authorized_keys`; do not rely on the SSH command exit code alone.
- If remote Codex/provider setup fails, do not claim the machine is fully ready for Codex App remote development.

## Success Response

Summarize only the operational facts:

- host alias
- whether passwordless SSH passed
- remote `codex` path/version
- `bubblewrap` sandbox smoke-test result
- cc-switch/provider configured
- remote `AGENTS.md` sync status
- remote Codex profile/config/rules generated
- suggested Codex App directory
- whether Codex App should be restarted
- any missing optional tools

End with the exact Codex App action: `Settings > Connections > select <alias> > choose <remote path>`.
