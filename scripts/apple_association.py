#!/usr/bin/env python3
"""Generate Apple signing and website association artifacts from product.json."""
import argparse
import json
import plistlib
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from carryon.product import cloud_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--entitlements', type=Path)
    parser.add_argument('--apns', default='development')
    parser.add_argument('--aasa', type=Path)
    parser.add_argument('--app-id')
    args = parser.parse_args()
    if args.entitlements:
        args.entitlements.parent.mkdir(parents=True, exist_ok=True)
        args.entitlements.write_bytes(plistlib.dumps({'aps-environment':args.apns or 'development',
            'com.apple.developer.associated-domains':['webcredentials:'+urlsplit(cloud_url()).hostname]}))
    if args.aasa:
        if not args.app_id: parser.error('--aasa requires --app-id TEAM_ID.BUNDLE_ID')
        args.aasa.parent.mkdir(parents=True, exist_ok=True)
        args.aasa.write_text(json.dumps({'webcredentials':{'apps':[args.app_id]}}, indent=2)+'\n')

if __name__ == '__main__': main()
