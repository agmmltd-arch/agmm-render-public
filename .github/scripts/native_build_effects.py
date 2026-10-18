"""Deny provider/network work in the unchanged native source-package child."""
import os
from pathlib import Path
import subprocess
import sys
from voice_effects import host


def install():
    host()
    original_run = subprocess.run
    root = Path(os.environ["AGMM_BUILD_ROOT"]).resolve()

    def command(args, kwargs):
        if kwargs.get("shell") or not isinstance(args, (list, tuple)):
            raise RuntimeError("hosted build forbids shell command execution")
        a = list(map(str, args))
        if Path(a[0]).name == "nice":
            if a[1:3] != ["-n", "15"]:
                raise RuntimeError("unexpected native nice command")
            a = a[3:]
        executable = Path(a[0]).name
        if executable not in ("ffmpeg", "ffprobe", "python3", "python", "tar"):
            raise RuntimeError("native build attempted a non-build/provider command")
        if any(x.startswith(("http:", "https:", "tcp:", "udp:", "ftp:")) for x in a):
            raise RuntimeError("native build attempted network media")
        if executable.startswith("python"):
            p = Path(a[1])
            p = p if p.is_absolute() else Path(kwargs.get("cwd") or os.getcwd()) / p
            if not p.resolve().is_relative_to(root) or p.suffix != ".py":
                raise RuntimeError("native Python build child outside pinned tree")

    def guarded_run(args, **kwargs):
        command(args, kwargs)
        return original_run(args, **kwargs)

    def audit(event, args):
        if event.startswith("socket.") or event in ("os.system", "os.exec", "os.posix_spawn"):
            raise RuntimeError("network/provider execution forbidden in native build")
        if event == "subprocess.Popen":
            command(args[1], {"cwd": args[2]})

    subprocess.run = guarded_run
    sys.addaudithook(audit)

