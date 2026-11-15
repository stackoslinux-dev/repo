#!/usr/bin/env python3
"""Native GNOME application lane; upstream code never receives signing credentials."""
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / 'compat'))
import cloud_cycle as c3
from native_component import compiler_bootstrap

OUT = Path('gnome-out')
ROOT = c3.ROOT
PREFIX = 'compat/zenity/'
PASS = 'PASS_NATIVE_C3_ZENITY_SOURCE_BUILD_AND_DIALOG'
CLIENT = 'PASS_NATIVE_C3_ZENITY_SIGNED_APT_AND_DIALOG'
UPSTREAM = 'https://download.gnome.org/sources/zenity/4.2/'
EPOCH = 1794614400


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(name, data):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')


def detect():
    listing = c3.download(UPSTREAM, 200000).decode()
    versions = set(re.findall(r'href="zenity-(4\.2\.[0-9]+)\.tar\.xz"', listing))
    assert versions, 'No approved stable GNOME source release found'
    version = max(versions, key=lambda x: tuple(map(int, x.split('.'))))
    filename = 'zenity-' + version + '.tar.xz'
    checksums = c3.download(UPSTREAM + 'zenity-' + version + '.sha256sum', 20000).decode()
    matches = re.findall(r'^([0-9a-f]{64})\s+' + re.escape(filename) + r'$', checksums, re.M)
    assert len(matches) == 1
    previous = None
    try:
        ref = json.loads(c3.download('https://api.github.com/repos/stackoslinux-dev/repo/git/ref/heads/c3-testing', 200000))
        commit = ref['object']['sha']
        assert re.fullmatch('[0-9a-f]{40}', commit)
        base = 'https://raw.githubusercontent.com/stackoslinux-dev/repo/' + commit + '/' + PREFIX
        previous = c3.verify_signed_bytes(c3.download(base + 'validated.json', 500000), c3.download(base + 'validated.json.asc', 100000))
        assert previous['package'] == 'zenity' and previous['client_status'] == CLIENT
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    changed = previous is None or subprocess.run(['dpkg', '--compare-versions', version, 'gt', previous['upstream_version']]).returncode == 0
    if previous and version == previous['upstream_version']:
        assert matches[0] == previous['source_sha256'], 'Upstream silently replaced a released source archive'
    refresh = bool(previous and not changed and datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(previous['signed_utc']) >= datetime.timedelta(hours=20))
    save('detection.json', {'package': 'zenity', 'version': version, 'url': UPSTREAM + filename,
                           'source_sha256': matches[0], 'previous': previous, 'changed': changed,
                           'refresh_due': refresh, 'build_required': changed or refresh,
                           'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           'coverage': 'Approved stable 4.2 branch only; new ABI/series requires review'})
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('changed=' + str(changed or refresh).lower() + '\n')


def gui(label, evidence):
    """Execute actual target GTK4 dialog, capture its window, verify its timeout."""
    OUT.mkdir(exist_ok=True)
    c3.native('/usr/bin/chmod', '1777', '/tmp')
    c3.native('/usr/bin/mkdir', '-p', '/tmp/.X11-unix')
    subprocess.run(['sudo', 'mount', '--bind', '/tmp/.X11-unix', str(ROOT / 'tmp/.X11-unix')], check=True)
    args = ['sudo', 'chroot', str(ROOT), '/usr/bin/env', 'DISPLAY=:99', 'GTK_A11Y=none',
            'GSK_RENDERER=cairo', 'GSETTINGS_BACKEND=memory', 'HOME=/root', 'LC_ALL=C',
            '/usr/bin/zenity', '--info', '--title=StackOS C3 native Zenity', '--text=' + label, '--timeout=12']
    with (OUT / (evidence + '.log')).open('w') as log:
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(60):
                if proc.poll() is not None:
                    raise AssertionError('Native GTK dialog exited before it could be observed')
                windows = subprocess.check_output(['xwininfo', '-display', ':99', '-root', '-tree'], text=True)
                if 'StackOS C3 native Zenity' in windows:
                    (OUT / (evidence + '-windows.txt')).write_text(windows)
                    subprocess.run(['import', '-display', ':99', '-window', 'root', str(OUT / (evidence + '.png'))], check=True)
                    break
                time.sleep(.1)
            else:
                raise AssertionError('Native GTK dialog window not found')
            assert proc.wait(timeout=20) == 5, 'Upstream timeout exit code must be 5'
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def sdk():
    manifest = json.loads((HERE / 'gnome-build-sdk.json').read_text())
    archive = HERE / manifest['archive']
    assert archive.stat().st_size == manifest['bytes'] and sha(archive) == manifest['sha256']
    # Strict allowlist: original native headers/tools, never runner libraries.
    with tarfile.open(archive) as tree:
        files = links = 0
        for entry in tree:
            parts = PurePosixPath(entry.name).parts
            assert parts and parts[0] == 'usr' and '..' not in parts and not PurePosixPath(entry.name).is_absolute()
            if entry.isfile():
                generated = {'usr/bin/' + n for n in ['ninja', 'glib-compile-resources', 'glib-compile-schemas', 'msgfmt', 'msgmerge', 'msginit', 'xgettext', 'xmllint', 'itstool']}
                generated.add('usr/libexec/c3-gnome-build/itstool.py')
                assert entry.name in manifest['source_files'] or entry.name in generated
                assert entry.size < 30_000_000
                # Generated wrappers are recorded by the archive hash; SDK files
                # additionally retain their individual original hashes.
                files += 1
            else:
                assert entry.issym() and manifest['links'][entry.name] == entry.linkname
                assert PurePosixPath(entry.linkname).name == entry.linkname
                links += 1
        assert files == manifest['files'] and links == len(manifest['links'])
    # Never override compiler bootstrap development links or glibc headers.
    subprocess.run(['sudo', 'tar', '--skip-old-files', '-xJf', str(archive), '-C', str(ROOT)], check=True)
    return manifest


def build():
    detection = json.loads((OUT / 'detection.json').read_text())
    assert detection['package'] == 'zenity' and re.fullmatch(r'4\.2\.[0-9]+', detection['version'])
    c3.bootstrap()
    compiler = compiler_bootstrap()
    manifest = sdk()
    archive = ROOT / 'work/source.tar.xz'
    archive.write_bytes(c3.download(detection['url'], 15_000_000))
    assert sha(archive) == detection['source_sha256']
    version = detection['version']
    with tarfile.open(archive) as source:
        for entry in source:
            parts = PurePosixPath(entry.name).parts
            assert parts[0] == 'zenity-' + version and '..' not in parts and not PurePosixPath(entry.name).is_absolute()
            assert entry.isfile() or entry.isdir(), 'Unexpected source link or device'
    subprocess.run(['sudo', 'tar', '-xJf', str(archive), '-C', str(ROOT / 'work')], check=True)
    c3.native('/usr/bin/mkdir', '-p', '/work/builder', '/work/tmp', '/work/stage')
    c3.native('/usr/bin/chown', '-R', '65000:65000', '/work')
    commands = [
        ['/usr/bin/python3', '-m', 'mesonbuild.mesonmain', 'setup', '/work/build', '/work/zenity-' + version,
         '--prefix=/usr', '--libdir=lib', '--buildtype=release', '-Dmanpage=false', '-Dwebkitgtk=false'],
        ['/usr/bin/ninja', '-C', '/work/build', '-j2'],
        ['/usr/bin/python3', '-m', 'mesonbuild.mesonmain', 'install', '-C', '/work/build', '--destdir', '/work/stage']]
    with (OUT / 'native-build.log').open('w') as log:
        for args in commands:
            subprocess.run(['sudo', 'chroot', '--userspec=65000:65000', str(ROOT), '/usr/bin/env', '-i',
                            'PATH=/usr/bin:/bin', 'HOME=/work/builder', 'TMPDIR=/work/tmp', 'LC_ALL=C',
                            'SOURCE_DATE_EPOCH=' + str(EPOCH), 'PKG_CONFIG_LIBDIR=/usr/lib/pkgconfig:/usr/share/pkgconfig',
                            'CFLAGS=-O2 -fPIC -ffile-prefix-map=/work=.',
                            'LDFLAGS=-Wl,-rpath-link,/usr/lib', *args], stdout=log, stderr=subprocess.STDOUT, check=True)
    stage = ROOT / 'work/stage'
    binary = stage / 'usr/bin/zenity'
    dynamic = subprocess.check_output(['readelf', '-d', str(binary)], text=True)
    assert 'RPATH' not in dynamic and 'RUNPATH' not in dynamic
    (OUT / 'native-elf-dynamic.txt').write_text(dynamic)
    # Genuine native C3 runtime files are already in the root seed; this CI DEB
    # depends on its actual aggregate owner, rather than fictitious providers.
    package_version = version + '+stackos1.c3.1'
    control = stage / 'DEBIAN'
    c3.native('/usr/bin/mkdir', '-p', '/work/stage/DEBIAN', '/work/stage/usr/share/doc/zenity')
    subprocess.run(['sudo', 'chown', '-R', str(os.getuid()) + ':' + str(os.getgid()), str(stage)], check=True)
    (control / 'control').write_text('Package: zenity\nVersion: ' + package_version + '\nArchitecture: amd64\nMaintainer: StackOS C3\nSection: gnome\nPriority: optional\nDepends: stackos-c3-runtime\nDescription: Native C3 GTK4 dialog utility built from genuine GNOME source\n')
    shutil.copy2(ROOT / ('work/zenity-' + version + '/COPYING'), stage / 'usr/share/doc/zenity/copyright')
    provenance = {'source_url': detection['url'], 'source_sha256': detection['source_sha256'], 'compiler': compiler,
                  'build_sdk_sha256': manifest['sha256'], 'webkit': 'upstream default disabled; no WebKit SDK',
                  'manpage': 'not built; upstream translated help included', 'runner_runtime_linked': False}
    (stage / 'usr/share/doc/zenity/C3-BUILD.json').write_text(json.dumps(provenance, indent=2) + '\n')
    files = sorted(p for p in stage.rglob('*') if p.is_file() and 'DEBIAN' not in p.relative_to(stage).parts)
    (control / 'md5sums').write_text(''.join(hashlib.md5(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(stage)) + '\n' for p in files))
    filename = 'zenity_' + package_version + '_amd64.deb'
    c3.native('/usr/bin/dpkg-deb', '--root-owner-group', '-Zxz', '--build', '/work/stage', '/work/' + filename)
    shutil.copy2(ROOT / 'work' / filename, OUT / filename)
    c3.native('/usr/bin/dpkg', '-i', '/work/' + filename)
    assert c3.native('/usr/bin/zenity', '--version').strip() == version
    assert not c3.native('/usr/bin/dpkg', '-V', 'zenity').strip()
    gui('Compiled from official GNOME ' + version + ' with native StackOS C3 GCC', 'native-build-dialog')
    save('build.json', {'status': PASS, 'package': 'zenity', 'version': package_version, 'upstream_version': version,
                        'filename': filename, 'sha256': sha(OUT / filename), 'binary_sha256': sha(binary),
                        'source_sha256': detection['source_sha256'], 'provenance': provenance,
                        'native_gui_timeout_exit': 5, 'production_modified': False})


if __name__ == '__main__':
    {'detect': detect, 'build': build}[sys.argv[1]]()
