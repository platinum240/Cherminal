"""Transports and a factory that builds one from a session profile."""

from __future__ import annotations

from ..config import SessionProfile, config_dir
from ..emulation import EMULATIONS
from .. import policy
from .base import Transport


def from_profile(profile: SessionProfile, ask_password=None, confirm_host_key=None,
                 ask_login=None) -> Transport:
    emu = EMULATIONS[profile.emulation]
    if profile.transport == "local":
        from .local import LocalTransport
        return LocalTransport(profile.command, term=emu.term_type)
    if profile.transport == "telnet":
        from .telnet import TelnetTransport
        return TelnetTransport(profile.host, profile.effective_port, term_type=emu.telnet_type,
                               tn3270=emu.block_mode, tls=profile.tls,
                               tls_verify=profile.tls_verify,
                               ca_file=policy.current().tls_ca_file)
    if profile.transport == "ssh":
        from .ssh import SSHTransport
        return SSHTransport(profile.host, profile.effective_port, profile.username,
                            profile.identity_file, term=emu.term_type,
                            known_hosts=config_dir() / "known_hosts",
                            ask_password=ask_password, confirm_host_key=confirm_host_key,
                            ask_login=ask_login if profile.ask_login else None)
    if profile.transport == "serial":
        from .serial import SerialTransport
        return SerialTransport(profile.serial_device, profile.baud, profile.data_bits,
                               profile.parity, profile.stop_bits, profile.flow_control)
    raise ValueError(f"unknown transport {profile.transport!r}")


__all__ = ["Transport", "from_profile"]
