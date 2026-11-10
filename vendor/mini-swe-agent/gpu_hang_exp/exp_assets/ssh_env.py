import os
import subprocess

from minisweagent.environments.local import LocalEnvironment, LocalEnvironmentConfig


class SshEnvironmentConfig(LocalEnvironmentConfig):
    host: str = "amd@172.31.8.11"
    port: int = 8022


class SshEnvironment(LocalEnvironment):
    """Executes bash commands on a remote host over SSH (passwordless or sshpass -e)."""

    def __init__(self, *, config_class: type = SshEnvironmentConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)
        cmd = [
            "ssh",
            "-p",
            str(self.config.port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            self.config.host,
        ]
        if os.environ.get("SSHPASS"):
            cmd = ["sshpass", "-e", *cmd]
        self._ssh_cmd = cmd
        self._remote_uname = self._exec_raw("uname -snrvm")

    def _exec_raw(self, remote_command: str, timeout: int = 30) -> str:
        try:
            result = subprocess.run(
                self._ssh_cmd + [remote_command], capture_output=True, text=True, timeout=timeout
            )
            return result.stdout
        except Exception:
            return ""

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict:
        command = action.get("command", "")
        cwd = cwd or self.config.cwd
        remote = f"cd '{cwd}' 2>/dev/null || true; {command}"
        try:
            result = subprocess.run(
                self._ssh_cmd + [remote],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout or self.config.timeout,
            )
            out = result.stdout.decode("utf-8", errors="replace")
            output = {"output": out, "returncode": result.returncode, "exception_info": ""}
        except subprocess.TimeoutExpired as e:
            raw = e.stdout or b""
            out = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            output = {
                "output": out,
                "returncode": -1,
                "exception_info": f"Command timed out after {timeout or self.config.timeout}s",
            }
        self._check_finished(output)
        return output

    def get_template_vars(self, **kwargs) -> dict:
        base = super().get_template_vars(**kwargs)
        parts = (self._remote_uname or "").split()
        if len(parts) >= 5:
            base |= {
                "system": parts[0],
                "node": parts[1],
                "release": parts[2],
                "version": " ".join(parts[3:-1]),
                "machine": parts[-1],
            }
        return base
