#!/usr/bin/env python3
"""Verify an existing signed C3 repository; never build or re-sign packages."""
import gzip
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

EXPECTED = '056F482818FF0BFCA93F31E28E5BDB912C8A2A16'

def run(*args):
    return subprocess.check_output(args, text=True)

def fields(text):
    rows = []
    row = {}
    last = None
    for line in text.splitlines() + ['']:
        if not line:
            if row:
                rows.append(row)
                row = {}
            last = None
        elif line[0].isspace():
            if last is None:
                raise ValueError('Invalid continuation')
            row[last] += '\n' + line[1:]
        else:
            name, value = line.split(':', 1)
            if name in row:
                raise ValueError('Duplicate field: ' + name)
            row[name] = value.strip()
            last = name
    return rows

def main(root):
    root = Path(root).resolve(strict=True)
    key = root / 'keys/stackos-archive-keyring.gpg'
    with tempfile.TemporaryDirectory() as home:
        listing = run('gpg', '--homedir', home, '--batch', '--show-keys', '--with-colons', str(key))
        primaries = []
        pending = False
        for line in listing.splitlines():
            parts = line.split(':')
            if parts[0] == 'pub':
                pending = True
            elif parts[0] == 'fpr' and pending:
                primaries.append(parts[9])
                pending = False
        if primaries != [EXPECTED]:
            raise ValueError('Unexpected archive key')
        def verify(signature, data=None):
            args = ['gpgv', '--homedir', home, '--keyring', str(key), str(signature)]
            if data is not None:
                args.append(str(data))
            subprocess.run(args, check=True)
        verify(root / 'InRelease')
        verify(root / 'Release.gpg', root / 'Release')
        # gpg decrypt emits exactly the signed plaintext after signature verification.
        signed = run('gpg', '--homedir', home, '--batch', '--no-default-keyring',
                     '--keyring', str(key), '--decrypt', str(root / 'InRelease'))
        release = (root / 'Release').read_text()
        if signed != release:
            raise ValueError('InRelease and Release disagree')
        meta = fields(release)[0]
        if meta.get('Origin') != 'StackOS' or meta.get('Codename') != 'c3':
            raise ValueError('Foreign release')
        checked = set()
        def verify_hash(name, size, digest):
            path = root / name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise ValueError('Unsafe or missing path: ' + name)
            if path.stat().st_size != int(size):
                raise ValueError('Size mismatch: ' + name)
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if not re.fullmatch('[0-9a-f]{64}', digest) or actual != digest:
                raise ValueError('SHA256 mismatch: ' + name)
            return path
        for line in meta.get('SHA256', '').splitlines():
            if not line.strip():
                continue
            digest, size, name = line.split()
            verify_hash(name, size, digest)
            checked.add(name)
        if not {'Packages', 'Packages.gz'} <= checked:
            raise ValueError('Unsigned package index')
        if gzip.decompress((root / 'Packages.gz').read_bytes()) != (root / 'Packages').read_bytes():
            raise ValueError('Compressed index differs')
        packages = fields((root / 'Packages').read_text())
        if not packages:
            raise ValueError('Empty package channel')
        seen = set()
        for package in packages:
            name = package['Package']
            identity = (name, package['Version'], package['Architecture'])
            if identity in seen or package['Architecture'] not in ('amd64', 'all', 'i386'):
                raise ValueError('Duplicate or unsupported package')
            seen.add(identity)
            path = verify_hash(package['Filename'], package['Size'], package['SHA256'])
            verify(Path(str(path) + '.asc'), path)
            actual = run('dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture')
            expected = ''.join(k + ': ' + package[k] + '\n' for k in ('Package', 'Version', 'Architecture'))
            if actual != expected:
                raise ValueError('DEB metadata differs: ' + name)
        for name in ('manifest.json', 'enable-c3-updates.py'):
            verify(root / (name + '.asc'), root / name)
        print('Verified', len(packages), 'signed C3 packages.')

if __name__ == '__main__':
    main(sys.argv[1])
