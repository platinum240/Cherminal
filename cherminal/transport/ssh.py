"""SSH via paramiko: key, agent and password/keyboard-interactive auth."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from .base import Transport

# ask_password(prompt) -> password or None to give up
PasswordPrompt = Callable[[str], "str | None"]
# confirm_host_key(host, key_type, sha256_fingerprint, changed) -> accept?
HostKeyPrompt = Callable[[str, str, str, bool], bool]


def fingerprint(key) -> str:
    import base64
    import hashlib
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class SSHTransport(Transport):
    def __init__(self, host: str, port: int = 22, username: str = "",
                 identity_file: str = "", term: str = "vt220",
                 known_hosts: Path | None = None,
                 ask_password: PasswordPrompt | None = None,
                 confirm_host_key: HostKeyPrompt | None = None):
        super().__init__()
        self.host, self.port = host, port
        self.username = username or os.environ.get("USER", "")
        self.identity_file = os.path.expanduser(identity_file) if identity_file else None
        self.term = term
        self.known_hosts = known_hosts
        self.ask_password = ask_password or (lambda prompt: None)
        self.confirm_host_key = confirm_host_key or (lambda *a: False)
        self.client = None
        self.chan = None

    def _open(self) -> None:
        import paramiko

        transport_self = self

        class AskPolicy(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client, hostname, key):
                if not transport_self.confirm_host_key(
                        hostname, key.get_name(), fingerprint(key), False):
                    raise paramiko.SSHException(f"host key for {hostname} was not accepted")
                client.get_host_keys().add(hostname, key.get_name(), key)
                if transport_self.known_hosts:
                    transport_self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
                    client.save_host_keys(str(transport_self.known_hosts))

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.known_hosts and self.known_hosts.exists():
            client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(AskPolicy())

        password = None
        for attempt in range(4):
            try:
                client.connect(self.host, self.port, username=self.username,
                               password=password, key_filename=self.identity_file,
                               allow_agent=True, look_for_keys=password is None,
                               timeout=15, banner_timeout=15, auth_timeout=30)
                break
            except paramiko.BadHostKeyException as e:
                raise OSError(f"host key for {self.host} has CHANGED (possible spoofing); "
                              f"refusing to connect. Offered key: {fingerprint(e.key)}") from e
            except paramiko.AuthenticationException:
                if attempt == 3:
                    raise OSError("authentication failed")
                password = self.ask_password(f"Password for {self.username}@{self.host}:")
                if password is None:
                    raise OSError("authentication cancelled")
        self.client = client
        self.chan = client.invoke_shell(term=self.term, width=self.cols, height=self.rows)

    def _read(self) -> bytes:
        return self.chan.recv(65536)

    def _write(self, data: bytes) -> None:
        self.chan.sendall(data)

    def resize(self, cols: int, rows: int) -> None:
        super().resize(cols, rows)
        if self.chan:
            self.chan.resize_pty(width=cols, height=rows)

    def _close(self) -> None:
        if self.client:
            self.client.close()
