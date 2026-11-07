#!/usr/bin/env python3
"""Acquire real compatibility component sources from authenticated source indexes.

This consumes source code and patches only. It never installs a foreign distro
or downloads its runtime binaries. Client APT sources are not modified.
"""
import argparse
import datetime
import email.utils
import hashlib
import json
import lzma
import re
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYRING = HERE / 'debian-source-keys.gpg'
MIRRORS = {
    'bookworm': 'https://deb.debian.org/debian/',
    'bookworm-security': 'https://security.debian.org/debian-security/',
}


def fetch(url, limit):
    assert url.startswith('https://')
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'StackOS-C3-Native-Source-Builder/1'})
            with urllib.request.urlopen(request, timeout=60) as response:
                assert response.url.startswith('https://')
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Source exceeds limit')
            return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(2 ** (attempt + 1))


def paragraphs(text):
    result = []
    current = {}
    previous = None
    for line in text.splitlines() + ['']:
        if not line:
            if current:
                result.append(current)
            current, previous = {}, None
        elif line[0].isspace():
            assert previous is not None
            current[previous] += '\n' + line.strip()
        else:
            key, value = line.split(':', 1)
            assert key not in current
            current[key] = value.strip()
            previous = key
    return result


def signed_index(suite, output):
    base = MIRRORS[suite]
    data = fetch(base + 'dists/' + suite + '/InRelease', 2_000_000)
    release = output / (suite + '-InRelease')
    release.write_bytes(data)
    subprocess.run(['gpgv', '--keyring', str(KEYRING), str(release)], check=True)
    # Do not parse the signature armor as release fields.
    text = data.decode().split('\n\n', 1)[1].split('-----BEGIN PGP SIGNATURE-----')[0]
    fields = paragraphs(text)[0]
    assert fields['Origin'] == 'Debian' and fields['Codename'] == suite
    now = datetime.datetime.now(datetime.timezone.utc)
    date = email.utils.parsedate_to_datetime(fields['Date'])
    assert date <= now + datetime.timedelta(days=1), 'Future source release'
    if suite.endswith('-security'):
        expires = email.utils.parsedate_to_datetime(fields['Valid-Until'])
        assert now < expires, 'Expired security index'
    hashes = [row.split() for row in fields['SHA256'].splitlines() if row.strip()]
    digest, size, name = next(row for row in hashes if row[2] == 'main/source/Sources.xz')
    assert re.fullmatch('[0-9a-f]{64}', digest)
    archive = fetch(base + 'dists/' + suite + '/' + name, 30_000_000)
    assert len(archive) == int(size) and hashlib.sha256(archive).hexdigest() == digest
    (output / (suite + '-Sources.xz')).write_bytes(archive)
    return paragraphs(lzma.decompress(archive).decode()), {
        'suite': suite, 'url': base + 'dists/' + suite + '/InRelease',
        'release_sha256': hashlib.sha256(data).hexdigest(),
        'sources_sha256': digest, 'signed_date': fields['Date'],
        'valid_until': fields.get('Valid-Until'),
    }


def acquire(package, output):
    assert package in ('libvpx', 'libotr', 'debianutils', 'psmisc', 'zenity')
    output.mkdir(parents=True, exist_ok=True)
    choices = []
    for suite in ('bookworm-security', 'bookworm'):
        rows, proof = signed_index(suite, output)
        for row in rows:
            if row['Package'] == package:
                choices.append((row, proof))
    assert choices, 'No authenticated source release'
    row, proof = choices[0]
    for candidate, evidence in choices[1:]:
        if subprocess.run(['dpkg', '--compare-versions', candidate['Version'], 'gt', row['Version']]).returncode == 0:
            row, proof = candidate, evidence
    assert re.fullmatch('[0-9A-Za-z.+:~_-]+', row['Version'])
    directory = row['Directory']
    assert re.fullmatch(r'pool/(?:updates/)?main/[a-z0-9]+/[a-z0-9+.-]+', directory)
    files = []
    for entry in row['Checksums-Sha256'].splitlines():
        if not entry.strip():
            continue
        digest, size, filename = entry.split()
        assert '/' not in filename and filename not in ('.', '..')
        assert re.fullmatch('[0-9a-f]{64}', digest)
        if not re.search(r'\.tar\.(?:gz|xz|bz2)$', filename):
            continue
        candidates = [MIRRORS[proof['suite']] + directory + '/' + filename]
        candidates.append('https://deb.debian.org/debian/pool/main/' + ('libv/' if package == 'libvpx' else 'libo/' if package == 'libotr' else package[0] + '/') + package + '/' + filename)
        data = None
        for url in dict.fromkeys(candidates):
            try:
                data = fetch(url, 100_000_000)
                break
            except urllib.error.HTTPError as error:
                if error.code != 404:
                    raise
        assert data is not None and len(data) == int(size)
        assert hashlib.sha256(data).hexdigest() == digest
        path = output / filename
        path.write_bytes(data)
        files.append({'file': filename, 'sha256': digest, 'bytes': int(size), 'url': url})
    assert files
    result = {'source_package': package, 'source_version': row['Version'], 'authentication': proof, 'files': files,
              'purpose': 'Compile from source with native C3 toolchain; no distro runtime binaries',
              'client_repository': 'https://stackoslinux-dev.github.io/repo/c3/'}
    (output / (package + '-source.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(acquire(args.package, args.output), indent=2))
