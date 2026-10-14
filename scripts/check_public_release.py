#!/usr/bin/env python3
"""Content-free checks for public source inventory, private markers and guide links."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check(verify_hashes=True):
    failures = []
    names = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).decode().split('\0')
    names = sorted(set(n for n in names if n))
    manifest = json.loads((ROOT / 'SOURCE_MANIFEST.json').read_text())
    for name, record in manifest['files'].items():
        path = ROOT / name
        if not path.is_file() or (verify_hashes and hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']):
            failures.append('source manifest mismatch: ' + name)
    public_files = {
        '.gitignore', '.gitattributes', 'README.md', 'AGENTS.md', 'CLAUDE.md', 'WORKFLOW.md', 'HANDOFF.md',
        'MAC_SETUP.md', 'MAC_RECOVERY.md', 'MAC_ONBOARDING_AGENT.md', 'ONBOARDING.md',
        'REFERENCE_GUIDE.md', 'GOOGLE_SETUP.md', 'ANDROID_RECOVERY.md', 'DRIVE_MIGRATION.md', 'OWNER_ARCHIVE.md',
        'HEALTH_ALERTS.md', 'GMKIT_MEDIA.md', 'LOOM_CAPTURE.md', 'CONTRIBUTING.md',
        'LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/AGPL-3.0.txt',
        'SOURCE_MANIFEST.json', 'scripts/check_public_release.py',
        '.github/workflows/source-checks.yml', 'MAINTENANCE.md', 'PHONE_SPAM.md',
        'information-site/.gitignore', 'information-site/.vercelignore',
        'information-site/README.md', 'information-site/vercel.json',
        'information-site/dist/index.html', 'information-site/dist/privacy.html',
        'information-site/dist/terms.html', 'information-site/dist/style.css',
    }
    for name in set(names) - set(manifest['files']) - public_files:
        failures.append('unexpected release file: ' + name)
    private_link = re.compile(rb'https://(?:docs\.google\.com/(?:document|spreadsheets)/d/|'
                              rb'drive\.google\.com/(?:drive/folders/|file/d/))[A-Za-z0-9_-]{25,}')
    # Patterns are deliberately broad enough for real credential shapes, while
    # synthetic short placeholder values in failure tests remain permissible.
    credential = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|'
                            rb'AIza[0-9A-Za-z_-]{30,}|ya29\.[0-9A-Za-z_-]{20,}|'
                            rb'gh[pousr]_[0-9A-Za-z]{30,}')
    for name in names:
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            failures.append('nonregular public path: ' + name)
            continue
        if path.suffix in {'.sqlite', '.sqlite3', '.db', '.zip', '.gz', '.png', '.jpg'} or name.startswith('.worktrees/'):
            failures.append('runtime or build artifact: ' + name)
        data = path.read_bytes()
        if private_link.search(data):
            failures.append('private document/folder link requires review: ' + name)
        if credential.search(data):
            failures.append('credential-shaped content requires review: ' + name)
        if path.suffix == '.md':
            text = data.decode()
            for target in re.findall(r'\]\(([^)]+)\)', text):
                if '://' in target or target.startswith(('mailto:', '#')):
                    continue
                target = target.split('#')[0]
                if target and not (path.parent / target).is_file():
                    failures.append('broken guide link: ' + name)
    return {'ok': not failures, 'reviewed_files': len(names),
            'manifest_files': len(manifest['files']), 'failures': sorted(set(failures))}


def refresh_manifest():
    result = check(verify_hashes=False)
    if not result['ok']:
        return result
    path = ROOT / 'SOURCE_MANIFEST.json'
    manifest = json.loads(path.read_text())
    for name, record in manifest['files'].items():
        record['sha256'] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    manifest['description'] = 'Reviewed canonical Minbox application and synthetic-test inventory.'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    return check()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-manifest', action='store_true',
                        help='Refresh reviewed existing source hashes after all other checks pass')
    args = parser.parse_args()
    result = refresh_manifest() if args.refresh_manifest else check()
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result['ok'] else 1)
