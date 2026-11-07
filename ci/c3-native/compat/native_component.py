#!/usr/bin/env python3
"""Build the real libvpx ABI7 compatibility component in native C3 userland.

Build credentials and signing credentials are deliberately separate jobs.
The upstream source code runs as uid65000 with a clean environment.
"""
import argparse
import datetime
import email.utils
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import cloud_cycle as c3
from fetch_native_sources import acquire

OUT = Path('compat-out')
ROOT = c3.ROOT
PACKAGE = 'libvpx7'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(name, data):
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')


def detect():
    source = acquire('libvpx', Path('authenticated-sources'))
    assert re.fullmatch(r'1\.12\.0-[0-9A-Za-z.+~]+', source['source_version']), 'ABI7 recipe requires qualification for a new upstream series'
    # This first lane adds a previously absent genuine compatibility library.
    # It does not manufacture an older package to pretend to demonstrate upgrade.
    previous = None
    try:
        ref = json.loads(c3.download('https://api.github.com/repos/stackoslinux-dev/repo/git/ref/heads/c3-testing', 200000))
        commit = ref['object']['sha']
        assert re.fullmatch('[0-9a-f]{40}', commit)
        base = 'https://raw.githubusercontent.com/stackoslinux-dev/repo/' + commit + '/compat/libvpx7/'
        data = c3.download(base + 'validated.json', 500000)
        previous = c3.verify_signed_bytes(data, c3.download(base + 'validated.json.asc', 100000))
        assert previous['package'] == PACKAGE and previous['client_status'] == 'PASS_NATIVE_C3_SIGNED_APT_CODEC_INSTALL'
    except __import__('urllib.error', fromlist=['HTTPError']).HTTPError as error:
        if error.code != 404:
            raise
    changed = previous is None or subprocess.run(['dpkg', '--compare-versions', source['source_version'], 'gt', previous['source_version']]).returncode == 0
    save('detection.json', {'package': PACKAGE, 'source': source, 'previous': previous,
                           'changed': changed, 'new_component': previous is None,
                           'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           'scope': 'Native ABI7 compatibility component; does not replace existing ABI11'})
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('changed=' + str(changed).lower() + '\n')
    print(json.dumps({'package': PACKAGE, 'source_version': source['source_version'], 'changed': changed}), flush=True)


def compiler_bootstrap():
    pointer = json.loads((HERE / 'compiler-cache.json').read_text())
    assert pointer['url'].startswith('https://github.com/stackoslinux-dev/repo/releases/download/')
    archive = Path('native-compiler-cache.tar.xz')
    archive.write_bytes(c3.download(pointer['url'], 150_000_000))
    assert archive.stat().st_size == pointer['bytes'] and sha(archive) == pointer['sha256']
    # A regular-file-only archive cannot install links pointing outside the root.
    count = 0
    with tarfile.open(archive) as source:
        for entry in source:
            parts = PurePosixPath(entry.name).parts
            assert entry.isfile() and parts and parts[0] == 'usr' and '..' not in parts
            assert entry.size < 100_000_000
            count += 1
    assert count == pointer['files']
    subprocess.run(['sudo', 'tar', '-xJf', str(archive), '-C', str(ROOT)], check=True)
    for name, target in [('cc','gcc'), ('c++','g++'), ('pkg-config','pkgconf')]:
        c3.native('/usr/bin/ln', '-sf', target, '/usr/bin/' + name)
    utils = pointer['build_utils']
    archive_utils = Path('native-build-utils.tar.xz')
    archive_utils.write_bytes(c3.download(utils['url'], 5_000_000))
    assert archive_utils.stat().st_size == utils['bytes'] and sha(archive_utils) == utils['sha256']
    with tarfile.open(archive_utils) as tree:
        members = tree.getmembers()
        assert len(members) == 1 and members[0].name == 'usr/bin/busybox' and members[0].isfile()
    subprocess.run(['sudo','tar','-xJf',str(archive_utils),'-C',str(ROOT)],check=True)
    for name in ['awk','sort','cut','wc','tr','xargs','od','hexdump','mktemp','expr','printf','which','seq','basename','dirname']:
        if not (ROOT/'usr/bin'/name).exists():c3.native('/usr/bin/ln','-s','busybox','/usr/bin/'+name)
    result = c3.native('/usr/bin/gcc', '--version')
    assert '15.2.0' in result
    print(result, flush=True)
    return {'archive_sha256': pointer['sha256'], 'gcc': result.splitlines()[0], 'native_userland': 'glibc2.42 / C3'}


def builder(*args, epoch):
    return subprocess.check_output([
        'sudo', 'chroot', '--userspec=65000:65000', str(ROOT), '/usr/bin/env', '-i',
        'PATH=/usr/bin:/bin:/usr/sbin:/sbin', 'HOME=/work/builder', 'TMPDIR=/work/tmp',
        'LC_ALL=C', 'SOURCE_DATE_EPOCH=' + str(epoch),
        'LD_LIBRARY_PATH=/work/libvpx-source',
        '/bin/sh', '-c', 'cd /work/libvpx-source && exec "$@"', 'c3-builder',
        *map(str, args)], text=True, stderr=subprocess.STDOUT)


def build():
    detection = json.loads((OUT / 'detection.json').read_text())
    assert detection['changed'] and detection['package'] == PACKAGE
    source = detection['source']
    c3.bootstrap()
    compiler = compiler_bootstrap()
    parent = ROOT / 'work'
    source_dir = parent / 'libvpx-source'
    unpack = Path('source-unpack')
    unpack.mkdir()
    for item in source['files']:
        archive = Path('authenticated-sources') / item['file']
        assert sha(archive) == item['sha256']
        with tarfile.open(archive) as stream:
            stream.extractall(unpack, filter='data')
    upstream = next(p for p in unpack.iterdir() if p.is_dir() and p.name.startswith('libvpx-'))
    shutil.move(upstream, source_dir)
    debian = unpack / 'debian'
    assert debian.is_dir()
    shutil.move(debian, source_dir / 'debian')
    patches = []
    for line in (source_dir / 'debian/patches/series').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name = line.split()[0]
        assert not name.startswith('/') and '..' not in PurePosixPath(name).parts
        patch = source_dir / 'debian/patches' / name
        assert patch.is_file() and not patch.is_symlink()
        subprocess.run(['patch', '--batch', '--forward', '-p1', '-i', str(patch.resolve())], cwd=source_dir, check=True)
        patches.append({'file': name, 'sha256': sha(patch)})
    changelog = (source_dir / 'debian/changelog').read_text()
    trailer = next(line for line in changelog.splitlines() if line.startswith(' -- '))
    epoch = int(email.utils.parsedate_to_datetime(trailer.rsplit('  ', 1)[1]).timestamp())
    assert 1262304000 < epoch < datetime.datetime.now(datetime.timezone.utc).timestamp() + 86400
    for directory in ['builder', 'tmp']:
        (parent / directory).mkdir()
    subprocess.run(['sudo', 'chown', '-R', '65000:65000', str(source_dir), str(parent / 'builder'), str(parent / 'tmp')], check=True)
    options = ['--target=x86_64-linux-gcc', '--prefix=/usr', '--libdir=/usr/lib',
               '--enable-shared', '--disable-static', '--enable-pic', '--disable-asm',
               '--disable-libyuv', '--disable-webm-io', '--disable-docs', '--disable-unit-tests']
    print(builder('./configure', *options, epoch=epoch), flush=True)
    print(builder('/usr/bin/make', '-j2', epoch=epoch), flush=True)
    library = next(p for p in source_dir.glob('libvpx.so.7.*') if p.is_file() and not p.is_symlink())
    first_hash = sha(library)
    print(builder('/usr/bin/make', 'clean', epoch=epoch), flush=True)
    print(builder('/usr/bin/make', '-j2', epoch=epoch), flush=True)
    assert sha(library) == first_hash, 'Native library rebuild is not reproducible'
    header = library.read_bytes()[:64]
    assert header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 62
    dynamic = subprocess.check_output(['readelf', '-d', str(library)], text=True)
    assert 'Library soname: [libvpx.so.7]' in dynamic
    assert not re.search(r'\((?:RPATH|RUNPATH)\)', dynamic), 'Personal/build path in runtime search'
    raw = bytes((x*17+y*11+frame*29+plane*53)%256 for frame in range(4) for plane in range(3) for y in range(32 if plane==0 else 16) for x in range(32 if plane==0 else 16))
    print(builder('/usr/bin/python3','-c','from pathlib import Path; Path("vector.yuv").write_bytes(bytes((x*17+y*11+f*29+p*53)%256 for f in range(4) for p in range(3) for y in range(32 if p==0 else 16) for x in range(32 if p==0 else 16)))',epoch=epoch),flush=True)
    print(builder('./vpxenc', '--codec=vp9', '--i420', '--lossless=1', '--threads=1', '--width=32', '--height=32', '--fps=30/1', '--limit=4', '--ivf', '-o', 'vector.ivf', 'vector.yuv', epoch=epoch), flush=True)
    print(builder('./vpxdec', '--codec=vp9', '--rawvideo', '--i420', '-o', 'decoded.yuv', 'vector.ivf', epoch=epoch), flush=True)
    assert (source_dir / 'decoded.yuv').read_bytes() == raw
    stage = parent / 'component-package'
    (stage / 'DEBIAN').mkdir(parents=True)
    (stage / 'usr/lib').mkdir(parents=True)
    shutil.copy2(library, stage / 'usr/lib' / library.name)
    (stage / 'usr/lib/libvpx.so.7').symlink_to(library.name)
    version = source['source_version'] + '+stackos1.c3.1'
    (stage / 'DEBIAN/control').write_text('Package: libvpx7\nVersion: ' + version + '\nArchitecture: amd64\nMaintainer: StackOS C3\nSection: libs\nPriority: optional\nDepends: stackos-c3-runtime (>= 10.8.2)\nDescription: Native C3 VP8 VP9 compatibility library, ABI7\n Compiled with native C3 GCC and glibc from authenticated source and security patches.\n')
    filename = PACKAGE + '_' + version + '_amd64.deb'
    for name in [filename, 'component-repro.deb']:
        print(c3.native('/usr/bin/env','SOURCE_DATE_EPOCH='+str(epoch),'/usr/bin/dpkg-deb', '--root-owner-group', '-Zxz', '--build', '/work/component-package', '/work/' + name), flush=True)
    assert sha(parent / filename) == sha(parent / 'component-repro.deb')
    print(c3.native('/usr/bin/dpkg', '-i', '/work/' + filename), flush=True)
    print(c3.native('/usr/bin/apt-get', 'check'), flush=True)
    installed = ROOT / 'usr/lib' / library.name
    assert sha(installed) == first_hash
    OUT.mkdir(exist_ok=True)
    shutil.copy2(parent / filename, OUT / filename)
    for tool in ['vpxenc', 'vpxdec']:
        shutil.copy2(source_dir / tool, OUT / tool)
    shutil.copy2(source_dir / 'vector.yuv', OUT / 'vector.yuv')
    record = {'status': 'PASS_NATIVE_C3_REPRODUCIBLE_LIBVPX7_CODEC_AND_DEB',
              'package': PACKAGE, 'version': version, 'source_version': source['source_version'],
              'filename': filename, 'sha256': sha(OUT / filename), 'soname': 'libvpx.so.7',
              'library_file': library.name, 'library_sha256': first_hash, 'source': source,
              'patches': patches, 'source_date_epoch': epoch, 'compiler': compiler,
              'codec_test': 'Four real YUV frames, VP9 lossless encode/decode exact equality',
              'native_binary_rebuild_reproducible': True,
              'security_references': sorted(set(re.findall(r'CVE-\d{4}-\d{4,}', changelog.split('\n\n', 2)[0] + '\n' + '\n'.join(p['file'] for p in patches)))),
              'replacement_of_existing_abi11': False, 'cloud_execution': bool(os.environ.get('GITHUB_ACTIONS'))}
    save('build.json', record)
    print(json.dumps(record, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['detect', 'build'])
    args = parser.parse_args()
    {'detect': detect, 'build': build}[args.action]()
