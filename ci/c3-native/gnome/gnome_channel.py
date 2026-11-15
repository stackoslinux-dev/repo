#!/usr/bin/env python3
"""Publish qualified GNOME packages only in a pinned, signed testing subchannel."""
from pathlib import Path
import base64
import datetime
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

import gnome_app as app
c3 = app.c3
OUT = app.OUT
CHANNEL = Path('gnome-channel')
REPO = 'stackoslinux-dev/repo'
BRANCH = 'c3-testing'


def read(path):
    return json.loads(Path(path).read_text())


def check(state):
    assert state['status'] == app.PASS and state['package'] == 'zenity'
    assert re.fullmatch(r'4\.2\.[0-9]+', state['upstream_version'])
    assert state['version'] == state['upstream_version'] + '+stackos1.c3.gcc.1'
    assert state['filename'] == 'zenity_' + state['version'] + '_amd64.deb'
    for key in ['sha256', 'binary_sha256', 'source_sha256']:
        assert re.fullmatch('[0-9a-f]{64}', state[key])
    assert state['native_gui_timeout_exit'] == 5 and state['production_modified'] is False
    assert state['provenance']['runner_runtime_linked'] is False


def verify(path):
    subprocess.run(['gpgv', '--keyring', str(Path('ci/c3-native/testing-keyring.gpg').resolve()), str(path) + '.asc', str(path)], check=True)


def sign():
    state = read(OUT / 'build.json')
    check(state)
    filename = state['filename']
    assert app.sha(OUT / filename) == state['sha256']
    CHANNEL.mkdir(exist_ok=True)
    shutil.copy2(OUT / filename, CHANNEL / filename)
    with c3.signing_key() as (home, fingerprint):
        now = datetime.datetime.now(datetime.timezone.utc)
        state.update(signing_fingerprint=fingerprint, channel=BRANCH, channel_subdirectory=app.PREFIX, signed_utc=now.isoformat())
        (CHANNEL / 'testing-keyring.gpg').write_bytes(subprocess.check_output(['gpg', '--homedir', home, '--batch', '--export', fingerprint]))
        fields = subprocess.check_output(['dpkg-deb', '-f', str(CHANNEL / filename)], text=True).rstrip()
        assert 'Package: zenity\n' in fields + '\n'
        packages = fields + '\nFilename: ' + filename + '\nSize: ' + str((CHANNEL / filename).stat().st_size) + '\nSHA256: ' + state['sha256'] + '\n\n'
        (CHANNEL / 'Packages').write_text(packages)
        (CHANNEL / 'Packages.gz').write_bytes(gzip.compress(packages.encode(), mtime=0))
        expiry = now + datetime.timedelta(days=7)
        release = 'Origin: StackOS\nLabel: StackOS C3 native GNOME testing\nSuite: c3-testing\nCodename: c3\nArchitectures: amd64\nDate: ' + now.strftime('%a, %d %b %Y %H:%M:%S +0000') + '\nValid-Until: ' + expiry.strftime('%a, %d %b %Y %H:%M:%S +0000') + '\nSHA256:\n'
        release += ''.join(' ' + app.sha(CHANNEL / name) + ' ' + str((CHANNEL / name).stat().st_size) + ' ' + name + '\n' for name in ['Packages', 'Packages.gz'])
        (CHANNEL / 'Release').write_text(release)
        for name, flag in [('InRelease', '--clearsign'), ('Release.gpg', '--detach-sign')]:
            subprocess.run(['gpg', '--homedir', home, '--batch', '--yes', '--local-user', fingerprint, '--digest-algo', 'SHA256', '--output', str(CHANNEL / name), flag, str(CHANNEL / 'Release')], check=True)
        c3.detach(home, fingerprint, CHANNEL / filename)
        (CHANNEL / 'state.json').write_text(json.dumps(state, indent=2) + '\n')
        c3.detach(home, fingerprint, CHANNEL / 'state.json')


def client():
    commit = os.environ['C3_TEST_SNAPSHOT']
    assert re.fullmatch('[0-9a-f]{40}', commit)
    base = 'https://raw.githubusercontent.com/' + REPO + '/' + commit + '/' + app.PREFIX
    state = c3.verify_signed_bytes(c3.download(base + 'state.json', 500000), c3.download(base + 'state.json.asc', 100000))
    check(state)
    assert state['channel'] == BRANCH and state['channel_subdirectory'] == app.PREFIX
    c3.bootstrap()
    root = c3.ROOT
    keyring = Path('ci/c3-native/testing-keyring.gpg')
    subprocess.run(['sudo', 'install', '-m', '644', str(keyring), str(root / 'usr/share/keyrings/stackos-testing.gpg')], check=True)
    source = root / 'work/gnome-testing.sources'
    source.write_text('Types: deb\nURIs: ' + base + '\nSuites: ./\nSigned-By: /usr/share/keyrings/stackos-testing.gpg\n')
    c3.native('/usr/bin/cp', '/work/gnome-testing.sources', '/etc/apt/sources.list.d/gnome-testing.sources')
    # This disposable client is restricted to the immutable signed HTTPS snapshot.
    # Production configuration and the user's disks are never touched.
    config = root / 'work/gnome-only.conf'
    config.write_text('Dir::Etc::sourcelist "/etc/apt/sources.list.d/gnome-testing.sources";\nDir::Etc::sourceparts "-";\n')
    c3.native('/usr/bin/cp', '/work/gnome-only.conf', '/etc/apt/apt.conf.d/99-gnome-only')
    update = c3.native('/usr/bin/apt-get', 'update')
    assert 'InRelease' in update and 'Packages' in update
    (OUT / 'signed-apt-update.log').write_text(update)
    policy = c3.native('/usr/bin/apt-cache', 'policy', 'zenity')
    assert state['version'] in policy
    (OUT / 'apt-policy.log').write_text(policy)
    previous = read(OUT / 'detection.json').get('previous')
    actual_upgrade = False
    if previous:
        check(previous)
        assert previous['client_status'] == app.CLIENT
        old_commit = previous['client']['publication_commit']
        assert re.fullmatch('[0-9a-f]{40}', old_commit)
        old_base = 'https://raw.githubusercontent.com/' + REPO + '/' + old_commit + '/' + app.PREFIX
        old = root / 'work' / previous['filename']
        old.write_bytes(c3.download(old_base + previous['filename']))
        assert app.sha(old) == previous['sha256']
        signature = OUT / 'previous-zenity.asc'
        signature.write_bytes(c3.download(old_base + previous['filename'] + '.asc', 100000))
        subprocess.run(['gpgv', '--keyring', str(keyring.resolve()), str(signature), str(old)], check=True)
        c3.native('/usr/bin/dpkg', '-i', '/work/' + old.name)
        assert subprocess.run(['dpkg', '--compare-versions', state['version'], 'ge', previous['version']]).returncode == 0, 'No downgrade'
        actual_upgrade = subprocess.run(['dpkg', '--compare-versions', state['version'], 'gt', previous['version']]).returncode == 0
    if actual_upgrade:
        offered = json.loads(c3.native('/usr/lib/stackos/stackos-updater-helper', 'check'))
        assert any(p['name'] == 'zenity' for p in offered['packages'])
        (OUT / 'updater-offered.json').write_text(json.dumps(offered, indent=2) + '\n')
        install = c3.native('/usr/lib/stackos/stackos-updater-helper', 'install')
    else:
        install = c3.native('/usr/bin/apt-get', 'install', '-y', '--no-install-recommends', 'zenity=' + state['version'])
    (OUT / 'apt-install.log').write_text(install)
    assert c3.native('/usr/bin/dpkg-query', '-W', '-f=${Version}', 'zenity') == state['version']
    assert not c3.native('/usr/bin/dpkg', '-V', 'zenity').strip()
    c3.native('/usr/bin/apt-get', 'check')
    assert app.sha(root / 'usr/bin/zenity') == state['binary_sha256']
    assert c3.native('/usr/bin/zenity', '--version').strip() == state['upstream_version']
    app.gui('Installed from signed HTTPS APT in native StackOS C3', 'signed-client-dialog')
    app.save('client.json', {'status': app.CLIENT, 'package': 'zenity', 'installed_version': state['version'],
                             'sha256': state['sha256'], 'binary_sha256': state['binary_sha256'],
                             'publication_commit': commit, 'signed_https_apt_install': True,
                             'actual_native_dialog': True, 'actual_updater_upgrade': actual_upgrade,
                             'first_install_not_updater_upgrade': previous is None,
                             'production_modified': False, 'owner_pc_or_ssd_required': False})


def approve():
    state = read(CHANNEL / 'state.json')
    check(state)
    verify(CHANNEL / 'state.json')
    evidence = read(OUT / 'client.json')
    assert evidence['status'] == app.CLIENT and evidence['installed_version'] == state['version'] and evidence['sha256'] == state['sha256']
    assert evidence['signed_https_apt_install'] and evidence['actual_native_dialog']
    state.update(client_status=app.CLIENT, client=evidence, validated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    with c3.signing_key() as (home, fingerprint):
        assert fingerprint == state['signing_fingerprint']
        (CHANNEL / 'validated.json').write_text(json.dumps(state, indent=2) + '\n')
        c3.detach(home, fingerprint, CHANNEL / 'validated.json')


def publish():
    state = read(CHANNEL / 'state.json')
    check(state)
    verify(CHANNEL / 'state.json')
    verify(CHANNEL / state['filename'])
    assert app.sha(CHANNEL / state['filename']) == state['sha256']
    assert state['channel'] == BRANCH and state['channel_subdirectory'] == app.PREFIX
    assert state['signing_fingerprint'] == Path('ci/c3-native/testing-key.fpr').read_text().strip()
    allowed = {'state.json', 'state.json.asc', 'testing-keyring.gpg', 'Packages', 'Packages.gz', 'Release', 'Release.gpg', 'InRelease', state['filename'], state['filename'] + '.asc'}
    if '--approved' in sys.argv:
        approved = read(CHANNEL / 'validated.json')
        verify(CHANNEL / 'validated.json')
        assert approved['client_status'] == app.CLIENT and approved['sha256'] == state['sha256']
        allowed |= {'validated.json', 'validated.json.asc'}
    token = os.environ['GH_TOKEN']
    def api(path, data=None, method=None):
        request = urllib.request.Request('https://api.github.com/repos/' + REPO + path, data=None if data is None else json.dumps(data).encode(), headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'StackOS-C3-native-GNOME'}, method=method)
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    head = api('/git/ref/heads/' + BRANCH)['object']['sha']
    tree = api('/git/commits/' + head)['tree']['sha']
    entries = []
    for path in sorted(CHANNEL.iterdir()):
        assert path.is_file() and not path.is_symlink() and path.name in allowed
        blob = api('/git/blobs', {'encoding': 'base64', 'content': base64.b64encode(path.read_bytes()).decode()})['sha']
        entries.append({'path': app.PREFIX + path.name, 'mode': '100644', 'type': 'blob', 'sha': blob})
    tree = api('/git/trees', {'base_tree': tree, 'tree': entries})['sha']
    commit = api('/git/commits', {'tree': tree, 'parents': [head], 'message': 'C3 native GNOME testing ' + ('validated: ' if '--approved' in sys.argv else 'candidate: ') + state['version']})['sha']
    api('/git/refs/heads/' + BRANCH, {'sha': commit, 'force': False}, 'PATCH')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('commit=' + commit + '\n')
    print(json.dumps({'commit': commit, 'prefix': app.PREFIX, 'production_modified': False}))


if __name__ == '__main__':
    {'sign': sign, 'client': client, 'approve': approve, 'publish': publish}[sys.argv[1]]()
