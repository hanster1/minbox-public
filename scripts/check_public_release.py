#!/usr/bin/env python3
"""Content-free checks for public source inventory, private markers and guide links."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

# Truncated SHA-256 of lowercase private words (household names and machine
# names). Stored as hashes so the denylist itself does not publish them.
PRIVATE_WORD_HASHES = {
    '01df2cc6fa6f8098',
    '0335aa820af252db',
    '20e09e434912381a',
    '2df7b03d1a69954f',
    '44f1a03440984278',
    '5d702eb07928ed7b',
    '7b2b547ab5377906',
    '9f27ff9b29865097',
    'c7566ba71fd4b99b',
    'c7c1319276e936c8',
    'f617936d4a0533db',
}
# Files where the maintainer's identity is intentionally public.
IDENTITY_ALLOWED = {'LICENSE'}
PUBLIC_CONTACT = b'spencer+minboxpublic@mail.grokbot.com'
WORD = re.compile(rb'[A-Za-z]{4,}')
# North American numbers outside the reserved fictional 555-01xx range.
PHONE = re.compile(rb'(?<![0-9])(?:\+?1[ .-]?)?\(?[2-9][0-9]{2}\)?[ .-]?(?!555)[2-9][0-9]{2}[ .-][0-9]{4}(?![0-9])'
                   rb'|\+1[2-9][0-9]{2}(?!555)[2-9][0-9]{6}(?![0-9])')
HOME_PATH = re.compile(rb'/(?:home|Users)/(?!(?:user|you|Alex|USER|PRIVATE|name)/)[A-Za-z0-9_.-]+/')
PRIVATE_EMAIL = re.compile(rb'(?<![A-Za-z0-9._%+-])(?!(?:person|example|someone|you)@)[A-Za-z0-9._%+-]+@(?:gmail|icloud|yahoo|outlook|hotmail)\.com')


def private_word_hits(data):
    hits = set()
    for word in WORD.findall(data):
        digest = hashlib.sha256(word.lower()).hexdigest()[:16]
        if digest in PRIVATE_WORD_HASHES:
            hits.add(digest)
    return hits


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
        'REFERENCE_GUIDE.md', 'READ_ONLY_SEARCH.md', 'PHONE_ACCESS.md', 'LOCAL_EXPORT.md', 'GOOGLE_SETUP.md', 'ANDROID_RECOVERY.md', 'DRIVE_MIGRATION.md', 'OWNER_ARCHIVE.md',
        'HEALTH_ALERTS.md', 'GMKIT_MEDIA.md', 'LOOM_CAPTURE.md', 'CONTRIBUTING.md',
        'LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/AGPL-3.0.txt',
        'SOURCE_MANIFEST.json', 'scripts/check_public_release.py',
        '.github/workflows/source-checks.yml', 'MAINTENANCE.md', 'PHONE_SPAM.md', 'ARCHITECTURE.md', 'PRIVACY.md',
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
        if name not in IDENTITY_ALLOWED and private_word_hits(data.replace(PUBLIC_CONTACT, b'')):
            failures.append('private name or machine name: ' + name)
        if PHONE.search(data):
            failures.append('real-looking phone number (use 555-01xx): ' + name)
        if HOME_PATH.search(data):
            failures.append('personal home-directory path: ' + name)
        if PRIVATE_EMAIL.search(data):
            failures.append('personal email address: ' + name)
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
