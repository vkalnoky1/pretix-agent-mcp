"""macOS login Keychain access without credentials in subprocess arguments.

The legacy generic-password API targets the user's login Keychain and works with
the same Python executable in the bootstrap, LaunchAgent and desktop helpers.
Never include API error details or credential buffers in diagnostics.
"""

from __future__ import annotations

import ctypes as C
import sys


def _security():
    if sys.platform != "darwin":
        raise RuntimeError("macOS Keychain is required")
    lib = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
    lib.SecKeychainAddGenericPassword.argtypes = [
        C.c_void_p,
        C.c_uint32,
        C.c_char_p,
        C.c_uint32,
        C.c_char_p,
        C.c_uint32,
        C.c_void_p,
        C.c_void_p,
    ]
    lib.SecKeychainAddGenericPassword.restype = C.c_int32
    lib.SecKeychainFindGenericPassword.argtypes = [
        C.c_void_p,
        C.c_uint32,
        C.c_char_p,
        C.c_uint32,
        C.c_char_p,
        C.POINTER(C.c_uint32),
        C.POINTER(C.c_void_p),
        C.c_void_p,
    ]
    lib.SecKeychainFindGenericPassword.restype = C.c_int32
    lib.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
    lib.SecKeychainItemFreeContent.restype = C.c_int32
    return lib


def add(service: str, account: str, value: str) -> None:
    """Create a new item. Refuse duplicates instead of replacing credentials."""
    lib = _security()
    name, user, secret = service.encode(), account.encode(), value.encode()
    status = lib.SecKeychainAddGenericPassword(
        None, len(name), name, len(user), user, len(secret), secret, None
    )
    if status:
        raise RuntimeError(f"Keychain item creation failed (status {status})")


def read(service: str, account: str) -> str:
    lib = _security()
    name, user = service.encode(), account.encode()
    length, buffer = C.c_uint32(), C.c_void_p()
    status = lib.SecKeychainFindGenericPassword(
        None, len(name), name, len(user), user, C.byref(length), C.byref(buffer), None
    )
    if status:
        raise RuntimeError(f"Keychain credential unavailable (status {status})")
    try:
        return C.string_at(buffer, length.value).decode()
    finally:
        lib.SecKeychainItemFreeContent(None, buffer)
