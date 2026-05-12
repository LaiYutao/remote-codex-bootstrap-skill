#!/usr/bin/env python3
"""Bootstrap a remote SSH host for Codex App remote development."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import subprocess
import sys
import base64
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_KEY_PATH = "~/.ssh/id_ed25519_codex"
DEFAULT_KEY_COMMENT = "codex-remote-dev-key"
DEFAULT_CC_API_KEY_ENV = "CODEX_REMOTE_CC_API_KEY"
REMOTE_TOOLS = ("git", "rg", "python3", "node", "uv")
CC_SWITCH_VERSION = "v5.5.0"
CC_SWITCH_ASSET = "cc-switch-cli-linux-x64.tar.gz"
REMOTE_DOWNLOAD_TIMEOUT_SECONDS = 60
CC_SWITCH_PATH_PREFIX = 'export PATH="$HOME/.local/bin:$PATH"; '
REMOTE_TURBO_PREFIX = (
    'if [ -f /etc/network_turbo ]; then '
    'source /etc/network_turbo >/dev/null 2>&1 || true; '
    'fi; '
)
REMOTE_TURBO_SUFFIX = (
    '; status=$?; '
    'unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; '
    'exit $status'
)
MINIMAL_CLI_PACKAGES = (
    "less ncurses-base ncurses-bin ncurses-term "
    "git openssh-client ca-certificates curl wget gnupg "
    "python3 python3-pip python3-venv python3-setuptools python3-wheel pipx "
    "ripgrep fd-find fzf jq bat tree tmux zoxide bubblewrap "
    "unzip zip tar gzip file rsync "
    "lsof procps psmisc iproute2 dnsutils netcat-openbsd iputils-ping "
    "vim nano"
)
BASH_ALIASES_CONTENT = """# Codex baseline CLI conveniences.

case "${TERM:-}" in
    ghostty|xterm-ghostty|ghostty-direct|xterm-ghostty-direct)
        export TERM=xterm-256color
        ;;
esac

alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias tb='[ -f /etc/network_turbo ] && source /etc/network_turbo || echo "/etc/network_turbo not found"'
alias us='unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY'

if command -v batcat >/dev/null 2>&1 && ! command -v bat >/dev/null 2>&1; then
    alias bat='batcat'
fi

if command -v fdfind >/dev/null 2>&1 && ! command -v fd >/dev/null 2>&1; then
    alias fd='fdfind'
fi

if command -v zoxide >/dev/null 2>&1; then
    eval "$(zoxide init bash)"
fi
"""


@dataclass(frozen=True)
class SshTarget:
    user: str
    host: str
    port: int


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        timeout=timeout,
    )


def parse_ssh_command(raw: str) -> SshTarget:
    parts = shlex.split(raw)
    if not parts or parts[0] != "ssh":
        raise ValueError("SSH command must start with 'ssh'")

    user_host: str | None = None
    port = 22
    user: str | None = None
    i = 1
    while i < len(parts):
        token = parts[i]
        if token in ("-p", "-l"):
            if i + 1 >= len(parts):
                raise ValueError(f"Missing value after {token}")
            if token == "-p":
                port = int(parts[i + 1])
            else:
                user = parts[i + 1]
            i += 2
            continue
        if token.startswith("-p") and len(token) > 2:
            port = int(token[2:])
            i += 1
            continue
        if token.startswith("-l") and len(token) > 2:
            user = token[2:]
            i += 1
            continue
        if token == "-o":
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        if user_host is None:
            user_host = token
        i += 1

    if not user_host:
        raise ValueError("Could not find user@host target in SSH command")
    if "@" in user_host:
        parsed_user, host = user_host.rsplit("@", 1)
        user = parsed_user or user
    else:
        host = user_host
    if not user:
        user = getpass.getuser()
    return SshTarget(user=user, host=host, port=port)


def default_alias(target: SshTarget) -> str:
    if target.host.endswith(".seetacloud.com"):
        return f"seetacloud-{target.port}"
    alias = re.sub(r"[^a-zA-Z0-9]+", "-", target.host.lower()).strip("-")
    return f"codex-{alias or 'remote'}-{target.port}"


def ensure_key(key_path: Path, comment: str) -> None:
    pub_path = Path(str(key_path) + ".pub")
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(key_path.parent, 0o700)
    if key_path.exists():
        if not pub_path.exists():
            public = run(["ssh-keygen", "-y", "-f", str(key_path)], check=True).stdout.strip()
            pub_path.write_text(public + "\n")
        return
    print(f"Creating reusable SSH key: {key_path}")
    run(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", comment], check=True)


def update_ssh_config(alias: str, target: SshTarget, key_path: Path) -> None:
    config_path = Path.home() / ".ssh" / "config"
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    text = config_path.read_text() if config_path.exists() else ""
    block_lines = [
        f"Host {alias}",
        f"  HostName {target.host}",
        f"  User {target.user}",
        f"  Port {target.port}",
        f"  IdentityFile {key_path}",
        "  IdentitiesOnly yes",
    ]
    block = "\n".join(block_lines)

    lines = text.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        if line.strip() == f"Host {alias}":
            out.extend(block_lines)
            replaced = True
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("Host "):
                i += 1
            continue
        out.append(line)
        i += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.extend(block_lines)
    config_path.write_text("\n".join(out).strip() + "\n")
    os.chmod(config_path, 0o600)
    print(f"Updated SSH config host: {alias}")


def ensure_codex_remote_feature() -> bool:
    path = Path.home() / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines()
    in_features = False
    has_features = False
    remote_line_index: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[features]":
            has_features = True
            in_features = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_features = False
        if in_features and re.match(r"remote_connections\s*=", stripped):
            remote_line_index = idx
            break
    if remote_line_index is not None and re.match(r"remote_connections\s*=\s*true\b", lines[remote_line_index].strip()):
        return False
    if remote_line_index is not None:
        lines[remote_line_index] = "remote_connections = true"
        path.write_text("\n".join(lines) + "\n")
        print("Enabled Codex remote_connections feature.")
        return True
    if has_features:
        out: list[str] = []
        inserted = False
        for line in lines:
            out.append(line)
            if line.strip() == "[features]" and not inserted:
                out.append("remote_connections = true")
                inserted = True
        path.write_text("\n".join(out) + ("\n" if out else ""))
    else:
        suffix = "" if text.endswith("\n") or not text else "\n"
        path.write_text(text + suffix + "\n[features]\nremote_connections = true\n")
    print("Enabled Codex remote_connections feature.")
    return True


def ssh(
    alias: str,
    remote_cmd: str,
    *,
    batch: bool = False,
    password: str | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = ["ssh"]
    if batch:
        cmd.extend(["-o", "BatchMode=yes"])
    if password is None:
        return run(cmd + [alias, remote_cmd], timeout=timeout)
    # Pass ssh argv through expect argv, not through Tcl string interpolation.
    # This keeps semicolons and quotes inside remote_cmd from being parsed locally.
    expect_script = """
set timeout 60
set cmd [lrange $argv 0 end]
spawn {*}$cmd
expect {
  -re {.*yes/no.*} {send "yes\\r"; exp_continue}
  -re {.*assword:.*} {send "$env(CODEX_REMOTE_PASSWORD)\\r"; exp_continue}
  eof
}
catch wait result
exit [lindex $result 3]
"""
    env = os.environ.copy()
    env["CODEX_REMOTE_PASSWORD"] = password
    # Some expect builds do not populate $argv for `expect -c` and instead try
    # to read the first SSH argv item as a script file. Use a real script file.
    with tempfile.NamedTemporaryFile("w", suffix=".expect", delete=False) as script_file:
        script_file.write(expect_script)
        script_path = script_file.name
    try:
        return subprocess.run(
            ["expect", script_path, *cmd, alias, remote_cmd],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)


def with_network_turbo(remote_cmd: str) -> str:
    return REMOTE_TURBO_PREFIX + remote_cmd + REMOTE_TURBO_SUFFIX


def passwordless_ok(alias: str) -> bool:
    result = ssh(alias, "hostname; pwd", batch=True)
    if result.returncode == 0:
        print("Passwordless SSH verified.")
        print(result.stdout.strip())
        return True
    return False


def install_public_key(alias: str, public_key: str, password: str) -> None:
    quoted_key = shlex.quote(public_key)
    remote_script = (
        "set -e; "
        "mkdir -p ~/.ssh; chmod 700 ~/.ssh; "
        "touch ~/.ssh/authorized_keys; chmod 600 ~/.ssh/authorized_keys; "
        f"grep -qxF {quoted_key} ~/.ssh/authorized_keys || "
        f"printf '%s\\n' {quoted_key} >> ~/.ssh/authorized_keys; "
        f"grep -qxF {quoted_key} ~/.ssh/authorized_keys"
    )
    result = ssh(alias, remote_script, password=password)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to install or verify public key:\n{result.stderr or result.stdout}")
    print("Installed and verified public key on remote host.")


def remote_workspace_for(user: str, override: str | None) -> str:
    if override:
        return override
    if user == "root":
        return "/root/workspace"
    return "~/workspace"


def run_remote_checks(alias: str, workspace_root: str, create_workspace: bool) -> None:
    workspace_cmd = ""
    if create_workspace:
        workspace_cmd = f"mkdir -p {shlex.quote(workspace_root)}; "
    tools = " ".join(REMOTE_TOOLS)
    check_script = (
        workspace_cmd
        + "echo '[host]'; hostname; "
        + "echo '[codex]'; (which codex && codex --version) || true; "
        + "echo '[tools]'; for t in "
        + tools
        + "; do if command -v $t >/dev/null 2>&1; then echo \"$t ok $(command -v $t)\"; else echo \"$t missing\"; fi; done"
    )
    result = ssh(alias, check_script, batch=True)
    if result.returncode != 0:
        raise RuntimeError(f"Remote readiness check failed:\n{result.stderr or result.stdout}")
    print(result.stdout.strip())


def verify_bubblewrap_sandbox(alias: str) -> bool:
    smoke = (
        "set -e; "
        "echo '[bubblewrap sandbox]'; "
        "command -v bwrap; bwrap --version; "
        "bwrap --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib "
        "--ro-bind /lib64 /lib64 --proc /proc --dev /dev --tmpfs /tmp "
        "/usr/bin/env -i PATH=/usr/bin:/bin sh -lc 'echo bwrap-ok; id -u; pwd'"
    )
    result = ssh(alias, smoke, batch=True)
    if result.returncode == 0 and "bwrap-ok" in result.stdout:
        print(result.stdout.strip())
        return True

    print(
        "[bubblewrap sandbox] unavailable: provider outer container blocks "
        "the namespace operations required by Codex sandboxing."
    )
    detail = (result.stderr or result.stdout).strip()
    if detail:
        print(detail)
    return False


def ensure_remote_codex(alias: str, target: SshTarget) -> None:
    check = ssh(alias, "command -v codex >/dev/null 2>&1 && codex --version", batch=True)
    if check.returncode == 0:
        print("[codex] already installed")
        print(check.stdout.strip())
        return
    if target.user != "root":
        raise RuntimeError("Remote codex is missing. Automatic Node.js/Codex installation is only enabled for root/no-sudo hosts.")
    print("[codex] not found; installing Node.js LTS and @openai/codex as root without /etc/network_turbo.")
    install_cmd = (
        "set -e; "
        "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; "
        "if ! command -v npm >/dev/null 2>&1; then "
        "apt-get update; "
        "apt-get install -y ca-certificates curl gnupg; "
        "curl -fsSL https://deb.nodesource.com/setup_lts.x | bash -; "
        "apt-get install -y nodejs; "
        "fi; "
        "npm config set registry https://registry.npmjs.org/; "
        "npm install -g @openai/codex; "
        "command -v codex; codex --version"
    )
    result = ssh(alias, install_cmd, batch=True)
    if result.returncode != 0:
        raise RuntimeError(f"Remote Codex installation failed:\n{result.stderr or result.stdout}")
    print(result.stdout.strip())


def ensure_shell_conveniences(alias: str, target: SshTarget) -> None:
    if target.user != "root":
        print("[shell] skipped default /root/.bash_aliases setup for non-root host.")
        return
    remote_cmd = (
        "cat > /root/.bash_aliases <<'EOF'\n"
        + BASH_ALIASES_CONTENT
        + "EOF\n"
        + "chmod 644 /root/.bash_aliases\n"
        + "env TERM=xterm-ghostty bash -ic 'echo \"ghostty-term=$TERM\"'\n"
    )
    result = ssh(alias, remote_cmd, batch=True)
    if result.returncode != 0:
        raise RuntimeError(f"Shell convenience setup failed:\n{result.stderr or result.stdout}")
    print("[shell]")
    print(result.stdout.strip())


def install_apt_packages(alias: str, target: SshTarget, packages: str, label: str, include_alias_checks: bool) -> None:
    if target.user != "root":
        print(f"[{label}] skipped package installation for non-root host.")
        return
    script = r'''
set -e
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get not found; package setup supports Ubuntu/Debian root hosts only." >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y __PACKAGES__
echo "[baseline versions]"
(node --version && npm --version && corepack --version) 2>/dev/null || true
echo "[terminfo]"
env TERM=xterm-256color clear >/dev/null && echo clear-ok
less --version | head -n 1
infocmp xterm-256color >/dev/null && echo terminfo-ok
echo "[ghostty]"
env TERM=xterm-ghostty bash -ic 'echo "$TERM"'
env TERM=xterm-ghostty bash -ic 'clear >/dev/null && echo clear-ok' || true
__ALIAS_CHECKS__
'''
    alias_checks = r'''
echo "[aliases]"
bash -ic 'type bat' || true
bash -ic 'type fd' || true
bash -ic 'type z' || true
''' if include_alias_checks else ""
    rendered = script.replace("__PACKAGES__", packages).replace("__ALIAS_CHECKS__", alias_checks)
    result = ssh(alias, rendered, batch=True)
    if result.returncode != 0:
        raise RuntimeError(f"{label} setup failed:\n{result.stderr or result.stdout}")
    print(f"[{label}]")
    print(result.stdout.strip())


def ensure_minimal_cli_tools(alias: str, target: SshTarget) -> None:
    install_apt_packages(alias, target, MINIMAL_CLI_PACKAGES, "minimal-cli", include_alias_checks=True)


def extract_cc_switch_from_remote_archive(alias: str, archive_path: str) -> subprocess.CompletedProcess[str]:
    remote_archive = shlex.quote(archive_path)
    return ssh(
        alias,
        "set -e; "
        + CC_SWITCH_PATH_PREFIX
        + "mkdir -p /root/.local/bin /tmp/cc-switch-install; "
        + "cd /tmp/cc-switch-install; "
        + "rm -f cc-switch; "
        + f"tar -xzf {remote_archive}; "
        + "cp cc-switch /root/.local/bin/cc-switch; "
        + "chmod +x /root/.local/bin/cc-switch; "
        + "ln -sf /root/.local/bin/cc-switch /usr/local/bin/cc-switch; "
        + CC_SWITCH_PATH_PREFIX
        + "cc-switch --version",
        batch=True,
    )


def ensure_cc_switch(alias: str, archive_path: str | None = None) -> None:
    check = ssh(alias, CC_SWITCH_PATH_PREFIX + "command -v cc-switch >/dev/null 2>&1 && cc-switch --version", batch=True)
    if check.returncode == 0:
        print("[cc-switch]")
        print(check.stdout.strip())
        return
    if archive_path:
        print(f"[cc-switch] installing from remote archive: {archive_path}")
        result = extract_cc_switch_from_remote_archive(alias, archive_path)
        if result.returncode != 0:
            raise RuntimeError(f"cc-switch archive installation failed:\n{result.stderr or result.stdout}")
        print(result.stdout.strip())
        return
    print(f"[cc-switch] not found; installing {CC_SWITCH_VERSION} from GitHub release tarball.")
    url = f"https://github.com/SaladDay/cc-switch-cli/releases/download/{CC_SWITCH_VERSION}/{CC_SWITCH_ASSET}"
    remote_archive = f"/tmp/{CC_SWITCH_ASSET}"
    download_cmd = (
        "set -e; "
        + CC_SWITCH_PATH_PREFIX
        + "mkdir -p /tmp/cc-switch-install; "
        + f"rm -f {shlex.quote(remote_archive)}; "
        + f"curl --max-time {REMOTE_DOWNLOAD_TIMEOUT_SECONDS} -fL --retry 1 -o {shlex.quote(remote_archive)} {shlex.quote(url)}"
    )
    direct_cmd = "unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY; " + download_cmd
    try:
        result = ssh(alias, direct_cmd, batch=True, timeout=REMOTE_DOWNLOAD_TIMEOUT_SECONDS + 30)
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess([], 124, "", "direct GitHub download timed out")
    if result.returncode != 0:
        print("[cc-switch] direct GitHub download failed; retrying with /etc/network_turbo fallback.")
        try:
            result = ssh(alias, with_network_turbo(download_cmd), batch=True, timeout=REMOTE_DOWNLOAD_TIMEOUT_SECONDS + 30)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess([], 124, "", "network_turbo GitHub download timed out")
    if result.returncode != 0:
        raise RuntimeError(
            "cc-switch remote GitHub download failed after direct and /etc/network_turbo attempts. "
            f"Agent recovery: download {CC_SWITCH_ASSET} locally with gh api, copy it to "
            f"{alias}:/tmp/{CC_SWITCH_ASSET}, then rerun this bootstrap command with "
            f"--skip-minimal-cli --cc-switch-archive /tmp/{CC_SWITCH_ASSET}.\n"
            + (result.stderr or result.stdout)
        )
    result = extract_cc_switch_from_remote_archive(alias, remote_archive)
    if result.returncode != 0:
        raise RuntimeError(f"cc-switch installation failed:\n{result.stderr or result.stdout}")
    print(result.stdout.strip())


def setup_cc_switch_provider(
    alias: str,
    provider_name: str,
    base_url: str,
    model: str,
    api_key: str,
    cc_switch_archive: str | None = None,
) -> None:
    ensure_cc_switch(alias, cc_switch_archive)
    remote_python = r'''
import base64
import json
import os
from pathlib import Path

provider_name = os.environ["CODEX_REMOTE_CC_PROVIDER"]
base_url = os.environ["CODEX_REMOTE_CC_BASE_URL"]
model = os.environ["CODEX_REMOTE_CC_MODEL"]
api_key = base64.b64decode(os.environ["CODEX_REMOTE_CC_API_KEY_B64"]).decode()
home = Path.home()
codex_dir = home / ".codex"
codex_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

auth_path = codex_dir / "auth.json"
auth = {}
if auth_path.exists():
    try:
        auth = json.loads(auth_path.read_text())
    except Exception:
        auth = {}
auth["OPENAI_API_KEY"] = api_key
auth_path.write_text(json.dumps(auth, indent=2) + "\n")
auth_path.chmod(0o600)

config_path = codex_dir / "config.toml"
config_text = (
    'model_provider = "custom"\n'
    f'model = "{model}"\n'
    'model_reasoning_effort = "medium"\n'
    'disable_response_storage = true\n'
    '\n'
    '[model_providers.custom]\n'
    'name = "custom"\n'
    'wire_api = "responses"\n'
    'requires_openai_auth = true\n'
    f'base_url = "{base_url}"\n'
)
config_path.write_text(config_text + "\n")
config_path.chmod(0o600)

cc_dir = home / ".cc-switch"
cc_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
print(f"Configured remote Codex default provider via {config_path}")
print(f"Provider label: {provider_name}")
print(f"Model: {model}")
'''
    remote_cmd = (
        CC_SWITCH_PATH_PREFIX
        + "CODEX_REMOTE_CC_PROVIDER="
        + shlex.quote(provider_name)
        + " CODEX_REMOTE_CC_BASE_URL="
        + shlex.quote(base_url)
        + " CODEX_REMOTE_CC_MODEL="
        + shlex.quote(model)
        + " CODEX_REMOTE_CC_API_KEY_B64="
        + shlex.quote(base64.b64encode(api_key.encode()).decode())
        + " python3 - <<'PY'\n"
        + remote_python
        + "PY"
    )
    result = ssh(alias, remote_cmd, batch=True)
    if result.returncode != 0:
        raise RuntimeError(f"Remote Codex provider configuration failed:\n{result.stderr or result.stdout}")
    print("[cc-switch/default Codex provider]")
    print(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-command", required=True, help="SSH command, for example: ssh -p 35842 root@example.com")
    parser.add_argument("--alias", help="SSH Host alias to add/update")
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH, help=f"Reusable SSH key path, default: {DEFAULT_KEY_PATH}")
    parser.add_argument("--workspace-root", help="Remote workspace root. Defaults to /root/workspace for root, ~/workspace otherwise.")
    parser.add_argument("--password", help="Temporary SSH password. Prefer --password-from-env when shell history exposure is a concern.")
    parser.add_argument("--password-from-env", help="Read the temporary SSH password from this environment variable.")
    parser.add_argument("--skip-remote", action="store_true", help="Only configure local files; skip remote key install and checks.")
    parser.add_argument("--skip-minimal-cli", action="store_true", help="Skip default minimal Ubuntu CLI package installation.")
    parser.add_argument("--cc-switch-archive", help="Remote path to a pre-copied cc-switch release tarball for resumable fallback installation.")
    parser.add_argument("--create-workspace", action="store_true", help="Create the suggested remote workspace directory.")
    parser.add_argument("--cc-provider-name", default="custom", help="cc-switch provider name.")
    parser.add_argument("--cc-base-url", default="https://api.openai.com/v1", help="Provider base URL.")
    parser.add_argument("--cc-model", default="gpt-5.5", help="Provider model.")
    parser.add_argument("--cc-api-key-from-env", default=DEFAULT_CC_API_KEY_ENV, help=f"Read provider API key from this environment variable. Default: {DEFAULT_CC_API_KEY_ENV}")
    args = parser.parse_args()

    target = parse_ssh_command(args.ssh_command)
    alias = args.alias or default_alias(target)
    key_path = Path(args.key_path).expanduser()
    pub_path = Path(str(key_path) + ".pub")
    workspace_root = remote_workspace_for(target.user, args.workspace_root)

    ensure_key(key_path, DEFAULT_KEY_COMMENT)
    update_ssh_config(alias, target, key_path)
    restart_needed = ensure_codex_remote_feature()

    if args.skip_remote:
        print("Skipped remote setup and checks.")
    else:
        if not passwordless_ok(alias):
            if args.password:
                password = args.password
            elif args.password_from_env:
                password = os.environ.get(args.password_from_env)
                if not password:
                    raise RuntimeError(f"Environment variable {args.password_from_env} is empty or unset")
            else:
                password = getpass.getpass("Temporary SSH password (not stored): ")
            public_key = pub_path.read_text().strip()
            install_public_key(alias, public_key, password)
            if not passwordless_ok(alias):
                raise RuntimeError("Passwordless SSH still failed after installing the public key")
        ensure_shell_conveniences(alias, target)
        if args.skip_minimal_cli:
            print("[minimal-cli] skipped by request.")
        else:
            ensure_minimal_cli_tools(alias, target)
        sandbox_ok = verify_bubblewrap_sandbox(alias)
        ensure_remote_codex(alias, target)
        run_remote_checks(alias, workspace_root, args.create_workspace)
        api_key = os.environ.get(args.cc_api_key_from_env)
        if not api_key:
            raise RuntimeError(f"Environment variable {args.cc_api_key_from_env} is empty or unset")
        setup_cc_switch_provider(alias, args.cc_provider_name, args.cc_base_url, args.cc_model, api_key, args.cc_switch_archive)

    print("\nCodex App remote connection:")
    print(f"  Host alias: {alias}")
    print(f"  Remote target: {target.user}@{target.host}:{target.port}")
    print(f"  Suggested directory: {workspace_root}")
    if not args.skip_remote and not sandbox_ok:
        print("  Bubblewrap sandbox: unavailable on this provider; continuing without sandbox support.")
    if restart_needed:
        print("  Restart Codex App so it reloads remote_connections = true.")
    print("  In Codex App: Settings > Connections > choose this host alias > select the remote directory.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
