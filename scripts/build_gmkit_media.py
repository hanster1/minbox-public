#!/usr/bin/env python3
"""Build the pinned AGPL gmkit media patch; never install or contact an account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

UPSTREAM = 'https://github.com/johnlindquist/gmkit.git'
COMMIT = 'c714f8ea1602d9c61876a87a44f6984ba3aeb4c4'
PATCH = Path(__file__).with_name('gmkit-media.patch')
# Applied in order on top of the pinned commit. Each later patch assumes the
# earlier ones; all remain AGPL-3.0-or-later like upstream gmkit.
PATCHES = [PATCH, Path(__file__).with_name('gmkit-spam-paging.patch')]
NOTICE = '''Minbox full-media and phone-spam metadata modification of gmkit v0.4.0 (2026-10-13)
Upstream: https://github.com/johnlindquist/gmkit
Pinned commit: c714f8ea1602d9c61876a87a44f6984ba3aeb4c4
License: GNU Affero General Public License version 3 or later (see LICENSE).
2026-10-15: phone Spam & blocked folder scan escalates its request size while the
folder is capped (gmkit-spam-paging.patch).
Modified source is included in gmkit-media-source.tar.gz; the patches are included
alongside it. Retain these source/license/provenance artifacts with any
binary distribution. This build includes no account credentials or archive data.
'''


def run(args, cwd=None, *, timeout=600, env=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, check=True, timeout=timeout,
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def validate_source(source):
    if run(['git', 'rev-parse', 'HEAD'], source) != COMMIT:
        raise ValueError('Source must be the pinned gmkit commit')
    if run(['git', 'status', '--porcelain'], source):
        raise ValueError('Source checkout must be clean')
    if run(['git', 'remote', 'get-url', 'origin'], source) != UPSTREAM:
        raise ValueError('Source origin must be official gmkit HTTPS repository')


def build(output, *, source=None, go='go'):
    output = Path(output).expanduser().absolute()
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('Build output must not use symlinks')
    if any((p / '.git').is_file() or (p / '.git' / 'HEAD').is_file() for p in (output, *output.parents)):
        raise ValueError('Build artifacts must remain outside Git')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty')
    output.mkdir(parents=True, mode=0o700, exist_ok=True)
    output.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix='minbox-gmkit-build-') as temporary:
        checkout = Path(temporary) / 'gmkit'
        if source is None:
            run(['git', 'clone', '--depth', '1', '--branch', 'v0.4.0', UPSTREAM, checkout], timeout=120)
        else:
            source = Path(source).resolve(strict=True)
            validate_source(source)
            run(['git', 'clone', '--no-hardlinks', source, checkout])
        if run(['git', 'rev-parse', 'HEAD'], checkout) != COMMIT:
            raise ValueError('Fetched gmkit commit does not match pin')
        for patch_file in PATCHES:
            run(['git', 'apply', '--check', patch_file], checkout)
            run(['git', 'apply', patch_file], checkout)
        env = {**os.environ, 'GOTOOLCHAIN': 'local', 'GOFLAGS': '-mod=readonly'}
        version = run([go, 'version'], env=env)
        run([go, 'test', './internal/media', './internal/gm', './internal/rpc', './internal/sync', './internal/store', './internal/cmd', './cmd/minbox-refresh-session'], checkout, env=env)
        run([go, 'build', '-trimpath', '-o', output / 'gmcli', './cmd/gmcli'], checkout, env=env)
        run([go, 'build', '-trimpath', '-o', output / 'minbox-refresh-session', './cmd/minbox-refresh-session'], checkout, env=env)
        shutil.copyfile(checkout / 'LICENSE', output / 'LICENSE')
        for patch_file in PATCHES:
            shutil.copyfile(patch_file, output / patch_file.name)
        upstream_notice = checkout / 'NOTICE'
        original_notice = upstream_notice.read_text() if upstream_notice.is_file() else ''
        (output / 'NOTICE').write_text(original_notice.rstrip() + '\n\n' + NOTICE if original_notice else NOTICE)
        with tarfile.open(output / 'gmkit-media-source.tar.gz', 'w:gz') as archive:
            for path in sorted(checkout.rglob('*')):
                if '.git' not in path.relative_to(checkout).parts:
                    archive.add(path, arcname=str(Path('gmkit-media') / path.relative_to(checkout)), recursive=False)
        artifacts = {p.name: digest(p) for p in output.iterdir() if p.is_file()}
        metadata = dict(upstream=UPSTREAM, commit=COMMIT, patch_sha256=digest(PATCH),
                        patches={p.name: digest(p) for p in PATCHES},
                        go_version=version, artifacts=artifacts,
                        checks=['pinned commit', 'clean source', 'git apply --check (ordered patch series)',
                                'go test media/gm/rpc/sync/store/cmd/refresh', 'go build -trimpath collector and refresh helper'],
                        installed=False)
        (output / 'provenance.json').write_text(json.dumps(metadata, indent=2) + '\n')
        for path in output.iterdir(): path.chmod(0o700 if path.name in ('gmcli', 'minbox-refresh-session') else 0o600)
        return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source', type=Path, help='clean official pinned checkout; avoids git network fetch')
    parser.add_argument('--go', default='go', help='Go 1.25+ executable; no automatic toolchain download')
    args = parser.parse_args()
    try:
        result = build(args.output, source=args.source, go=args.go)
    except (OSError, ValueError, subprocess.SubprocessError):
        parser.exit(1, 'Build failed; no collector was installed.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
