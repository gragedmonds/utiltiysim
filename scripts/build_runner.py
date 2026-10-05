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
import time
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def smoke_startup(executable, library):
    """The GUI entry point must work too, not just the simulation self-test."""
    ready = library / 'startup-ready.json'
    ready.unlink(missing_ok=True)
    with (library / 'startup.log').open('w') as log:
        process = subprocess.Popen([str(executable), '--store', str(library), '--port', '0',
                                    '--ready-file', str(ready)], cwd=library, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 45
            with httpx.Client(timeout=1, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError((library / 'startup.log').read_text())
                    try:
                        address = urlparse(json.loads(ready.read_text())['url'])
                        origin = 'http://' + address.netloc
                        headers = {'Authorization': 'Bearer ' + parse_qs(address.fragment)['token'][0]}
                        response = client.get(origin + '/local/status', headers=headers)
                        if response.status_code == 200:
                            assert response.json()['schemaVersion'] == 'local-status/2.0'
                            assert client.get(origin + '/').status_code == 200
                            assert client.get(origin + '/setup.js').status_code == 200
                            assert 'Starting point' in client.get(origin + '/setup.js').text
                            desktop = client.get(origin + '/local-runs.html').text
                            assert 'Activity sequences</a>' in desktop and '>Map</a>' not in desktop
                            graph = client.get(origin + '/api/dependencies').json()
                            assert graph == client.get(origin + '/dependency-graph.json').json()
                            assert all(e.get('explanation') for e in graph['edges'])
                            assert client.get(origin + '/packs/index.json').status_code == 200
                            assert client.get(origin + '/api/health').status_code == 200
                            assert client.get(origin + '/local/status').status_code == 401
                            print('Packaged server startup, Studio pages, engine API and authenticated readiness passed.')
                            return
                    except (OSError, ValueError, httpx.HTTPError):
                        pass
                    time.sleep(.2)
                raise RuntimeError('Packaged server did not become ready: ' + (library / 'startup.log').read_text())
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            ready.unlink(missing_ok=True)


def signing_key():
    """The release key (RUNTIME_SIGNING_KEY: an OpenSSH ed25519 private key, the workflow's secret) when it matches
    the public key the launcher embeds (launcher/release_key.pub), so launchers already installed trust this
    release's runtime and update to it. Without it, a throwaway key signs the runtime for this build's own launcher
    only, and installed launchers leave this release alone."""
    secret = os.environ.get('RUNTIME_SIGNING_KEY', '').strip()
    committed = (ROOT / 'launcher' / 'release_key.pub').read_text().strip()
    if not secret:
        print('RUNTIME_SIGNING_KEY is not set: signing with a throwaway key; installed launchers will not auto-update to this build.')
        return Ed25519PrivateKey.generate(), False
    private = serialization.load_ssh_private_key(secret.encode(), password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise SystemExit('RUNTIME_SIGNING_KEY must be an ed25519 key (ssh-keygen -t ed25519).')
    if not committed:
        raise SystemExit('RUNTIME_SIGNING_KEY is set but launcher/release_key.pub is empty: commit the public key first.')
    expected = committed.split()[1]
    actual = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode().split()[1]
    if expected != actual:
        raise SystemExit('RUNTIME_SIGNING_KEY does not match launcher/release_key.pub: launchers would not trust this release.')
    return private, True


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
               '--hidden-import', 'utilsim.batch', '--hidden-import', 'utilsim.gen.pipeline', '--hidden-import', 'api.app',
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
    private, signed_for_updates = signing_key()
    public = base64.b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    sig = base64.b64encode(private.sign(sha.encode())).decode()
    values = {'runtimeURL': f'https://github.com/gragedmonds/utiltiysim/releases/download/{args.tag}/{runtime.name}',
              'runtimeSHA': sha, 'runtimeSignature': sig, 'runtimePublicKey': public,
              'runtimeBytes': str(runtime.stat().st_size), 'releaseVersion': args.tag, 'platformTag': target}
    name = 'UtilityStudio-' + target + ('.exe' if system == 'windows' else '')
    launcher = out / name
    flags = '-s -w ' + ' '.join('-X main.' + key + '=' + value for key, value in values.items())
    if system == 'windows':
        flags += ' -H=windowsgui'  # no console window: the launcher page in the browser is the window
    subprocess.run(['go', 'build', '-trimpath', '-ldflags', flags, '-o', str(launcher), '.'], cwd=ROOT / 'launcher', check=True)
    if system != 'windows':
        # Browser downloads do not preserve executable mode. A zip preserves it on extraction.
        with zipfile.ZipFile(out / (name + '.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(launcher, name)
        launcher.unlink()
        launcher = out / (name + '.zip')
    (out / ('manifest-' + target + '.json')).write_text(json.dumps({**values, 'platform': target,
        'engineBuild': build_file.read_text(), 'launcherBytes': launcher.stat().st_size,
        'launcherSha256': hashlib.sha256(launcher.read_bytes()).hexdigest(), 'signedForUpdates': signed_for_updates}, indent=2))
    print(json.dumps({'platform': target, 'runtimeBytes': runtime.stat().st_size, 'launcherBytes': launcher.stat().st_size}))
    # Smoke the packaged engine, without Python or a terminal being required by the end user.
    executable = ROOT / 'dist/utility-runner' / ('utility-runner.exe' if system == 'windows' else 'utility-runner')
    library = ROOT / 'build' / 'smoke-library'
    library.mkdir(exist_ok=True)
    subprocess.run([str(executable), '--self-test', str(library)], check=True)
    smoke_startup(executable, library)


if __name__ == '__main__':
    main()
