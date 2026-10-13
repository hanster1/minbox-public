#!/usr/bin/env python3
"""Receive Gmail app password on stdin, test delivery, then save private config."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from health_monitor import atomic_json, send_notification


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[A-Za-z0-9._%+-]+@gmail\.com', args.address):
            raise ValueError('invalid address')
        password = ''.join(sys.stdin.read(1024).split())
        if not re.fullmatch(r'[a-zA-Z]{16}', password):
            print('Expected a 16-letter Google app password; configuration unchanged.')
            return 1
        path = Path.home() / '.config/minbox-text-archive/health.json'
        if path.is_symlink() or path.stat().st_mode & 0o777 != 0o600:
            raise ValueError('private configuration required')
        config = json.loads(path.read_text())
        delivery = dict(type='smtp', host='smtp.gmail.com', port=465, security='ssl',
                        username=args.address, password=password,
                        **{'from': args.address, 'to': args.address})
        send_notification(delivery, 'Minbox emergency notifications: delivery test. Only unresolved incidents needing human intervention will be sent here; routine failures and recoveries remain local. No message contents are included.')
        config['delivery'] = delivery
        atomic_json(path, config)
        print('Test email accepted by Gmail; private emergency configuration saved.')
        return 0
    except Exception:
        print('Email setup failed; configuration unchanged. Check the app password, Google account eligibility, and SMTP connectivity.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
