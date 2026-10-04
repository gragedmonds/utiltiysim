"""Build a self-contained runtime and a small launcher pinned to its signed digest."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    system = {'Windows': 'windows', 'Darwin': 'macos', 'Linux': 'linux'}[platform.system()]
    arch = 'arm64' if platform.machine().lower() in ('arm64', 'aarch64') else 'x64'
    target = system + '-' + arch
    out = ROOT / 'dist' / 'release'
    out.mkdir(parents=True, exist_ok=True)
    from utilsim.io.run_bundle import engine_build
    build_file = ROOT / 'build' / 'engine-build.txt'
    build_file.parent.mkdir(exist_ok=True)
    build_file.write_text(engine_build())
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'utility-runner',
               '--hidden-import', 'utilsim.batch', '--hidden-import', 'utilsim.gen.pipeline',
               '--collect-data', 'utilsim', '--copy-metadata', 'numpy', '--copy-metadata', 'pydantic',
               '--copy-metadata', 'orjson', '--exclude-module', 'matplotlib', '--exclude-module', 'pyarrow']
    for source, dest in [(ROOT / 'packages/town-viewer/dist', 'packages/town-viewer/dist'),
                         (ROOT / 'utilsim/config/presets', 'utilsim/config/presets'),
                         (ROOT / 'packs', 'packs'), (ROOT / 'schemas', 'schemas'), (build_file, '.')]:
        command += ['--add-data', str(source) + os.pathsep + dest]
    command += [str(ROOT / 'utilsim/worker/entry.py')]
    subprocess.run(command, cwd=ROOT, check=True)
    runtime = out / ('runtime-' + target + '.zip')
    with zipfile.ZipFile(runtime, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted((ROOT / 'dist/utility-runner').rglob('*')):
            if file.is_file():
                # Dereference PyInstaller symlinks: extraction never creates filesystem links.
                name = file.relative_to(ROOT / 'dist/utility-runner').as_posix()
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o100700 if os.access(file, os.X_OK) else 0o100600) << 16
                archive.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    sha = hashlib.sha256(runtime.read_bytes()).hexdigest()
    # Per-release signing key: only the public key is embedded, the private key is never saved or uploaded.
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    sig = base64.b64encode(private.sign(sha.encode())).decode()
    values = {'runtimeURL': f'https://github.com/gragedmonds/utiltiysim/releases/download/{args.tag}/{runtime.name}',
              'runtimeSHA': sha, 'runtimeSignature': sig, 'runtimePublicKey': public,
              'runtimeBytes': str(runtime.stat().st_size), 'releaseVersion': args.tag}
    name = 'UtilityStudio-' + target + ('.exe' if system == 'windows' else '')
    launcher = out / name
    flags = '-s -w ' + ' '.join('-X main.' + key + '=' + value for key, value in values.items())
    subprocess.run(['go', 'build', '-trimpath', '-ldflags', flags, '-o', str(launcher), '.'], cwd=ROOT / 'launcher', check=True)
    if system != 'windows':
        # Browser downloads do not preserve executable mode. A zip preserves it on extraction.
        with zipfile.ZipFile(out / (name + '.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(launcher, name)
        launcher.unlink()
        launcher = out / (name + '.zip')
    (out / ('manifest-' + target + '.json')).write_text(json.dumps({**values, 'platform': target,
        'engineBuild': build_file.read_text(), 'launcherBytes': launcher.stat().st_size,
        'launcherSha256': hashlib.sha256(launcher.read_bytes()).hexdigest()}, indent=2))
    print(json.dumps({'platform': target, 'runtimeBytes': runtime.stat().st_size, 'launcherBytes': launcher.stat().st_size}))
    # Smoke the packaged engine, without Python or a terminal being required by the end user.
    executable = ROOT / 'dist/utility-runner' / ('utility-runner.exe' if system == 'windows' else 'utility-runner')
    library = ROOT / 'build' / 'smoke-library'
    library.mkdir(exist_ok=True)
    subprocess.run([str(executable), '--self-test', str(library)], check=True)


if __name__ == '__main__':
    main()
