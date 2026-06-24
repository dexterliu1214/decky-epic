#!/usr/bin/env python3
"""On-device backend smoke test.

Run this ON THE STEAM DECK (or any Linux box with Python >= 3.10) to validate the
vendored backend before exercising the full plugin:

    cd ~/homebrew/plugins/decky-epic
    python3 scripts/smoke_backend.py

It checks: vendored deps import, the native pycryptodomex loads, legendary's
LegendaryCore constructs against an isolated config, and Proton discovery works.
It does NOT log in, download, or sync — it just proves the runtime is sound.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))

# Isolate legendary config so this never touches a real ~/.config/legendary.
os.environ.setdefault("DECKY_PLUGIN_SETTINGS_DIR", os.path.join(ROOT, ".smoke", "settings"))
os.environ.setdefault("DECKY_PLUGIN_RUNTIME_DIR", os.path.join(ROOT, ".smoke", "runtime"))


def main() -> int:
    print(f"python: {sys.version}")

    print("importing vendored deps...", end=" ")
    import requests  # noqa
    import filelock  # noqa
    from Cryptodome.Cipher import AES  # noqa  (native pycryptodomex)
    print("ok")

    print("importing legendary...", end=" ")
    from legendary.core import LegendaryCore
    import legendary
    print(f"ok (v{legendary.__version__})")

    print("constructing LegendaryCore (isolated config)...", end=" ")
    from epic import paths
    paths.apply_legendary_env()
    core = LegendaryCore()
    print(f"ok -> {os.environ['LEGENDARY_CONFIG_PATH']}")

    print("has stored credentials:", bool(core.lgd.userdata))

    print("discovering Proton builds...")
    from epic import proton
    builds = proton.discover_proton_builds()
    if builds:
        for b in builds[:5]:
            print(f"  - {b['name']}  ({b['path']})")
    else:
        print("  (none found — install Proton/GE-Proton via Steam)")

    print("\nSMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
