"""Transports and a factory that builds one from a session profile."""

from __future__ import annotations

from .. import policy, system
from ..config import SessionProfile, config_dir, site_dirs
from ..emulation import EMULATIONS
from .base import Transport

# Host keys every user trusts: the system's OpenSSH file, then a
# known_hosts file in each shared setup folder.
SYSTEM_KNOWN_HOSTS = system.system_known_hosts()


def from_profile(profile: SessionProfile, ask_password=None, confirm_host_key=None,
                 ask_login=None) -> Transport:
    transport = _make(profile, ask_password, confirm_host_key, ask_login)
    transport.keepalive = profile.keepalive
    return transport


def _make(profile, ask_password, confirm_host_key, ask_login) -> Transport:
    emu = EMULATIONS[profile.emulation]
    if profile.transport == "local":
        if system.IS_WINDOWS:
            from .conpty import ConPtyTransport
            return ConPtyTransport(profile.command, term=emu.term_type)
        from .local import LocalTransport
        return LocalTransport(profile.command, term=emu.term_type)
    if profile.transport == "telnet":
        from .telnet import TelnetTransport
        return TelnetTransport(profile.host, profile.effective_port, term_type=emu.telnet_type,
                               tn3270=emu.block_mode, tls=profile.tls,
                               device_name=profile.device_name if emu.family == "ibm5250" else "",
                               tls_verify=profile.tls_verify,
                               ca_file=policy.current().tls_ca_file,
                               # TN3270E for printers, and for displays given an LU name
                               tn3270e=getattr(emu, "tn3270", False)
                               and (emu.printer or bool(profile.lu_name)),
                               lu_name=profile.lu_name, printer=emu.printer)
    if profile.transport == "ssh":
        from .ssh import SSHTransport
        return SSHTransport(profile.host, profile.effective_port, profile.username,
                            profile.identity_file, term=emu.term_type,
                            known_hosts=config_dir() / "known_hosts",
                            ask_password=ask_password, confirm_host_key=confirm_host_key,
                            ask_login=ask_login if profile.ask_login else None,
                            trusted_known_hosts=[SYSTEM_KNOWN_HOSTS]
                            + [d / "known_hosts" for d in site_dirs()],
                            strict=policy.current().ssh_known_hosts_only)
    if profile.transport == "serial":
        from .serial import SerialTransport
        return SerialTransport(profile.serial_device, profile.baud, profile.data_bits,
                               profile.parity, profile.stop_bits, profile.flow_control)
    raise ValueError(f"unknown transport {profile.transport!r}")


__all__ = ["Transport", "from_profile"]
