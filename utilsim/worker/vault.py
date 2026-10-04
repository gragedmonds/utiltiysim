"""Secrets (the Anthropic API key for Talk it through) live outside archives. Native vault on Windows/macOS; private file on Linux."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def save(path: Path, token: str):
    if sys.platform == 'darwin':
        subprocess.run(['security', 'add-generic-password', '-U', '-a', str(path), '-s', 'UtilityStudio', '-w', token],
                       check=True, capture_output=True)
        return
    raw = token.encode()
    if sys.platform == 'win32':
        raw = windows_protect(raw, False)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def read(path: Path):
    if sys.platform == 'darwin':
        result = subprocess.run(['security', 'find-generic-password', '-a', str(path), '-s', 'UtilityStudio', '-w'],
                                capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    if not path.exists():
        return None
    raw = path.read_bytes()
    if sys.platform == 'win32':
        raw = windows_protect(raw, True)
    return raw.decode()


def windows_protect(data: bytes, decrypt: bool):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError('Windows could not unlock the device credential.')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def clear(path: Path):
    if sys.platform == 'darwin':
        subprocess.run(['security', 'delete-generic-password', '-a', str(path), '-s', 'UtilityStudio'], capture_output=True)
        return
    path.unlink(missing_ok=True)
