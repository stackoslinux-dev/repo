#!/usr/bin/env python3
from pathlib import Path
import os,subprocess
if os.geteuid()!=0:raise SystemExit('Execute com sudo.')
if not any('StackOS C3' in p.read_text(errors='replace') for p in [Path('/etc/stackos-build'),Path('/etc/os-release')] if p.exists()):raise SystemExit('Este canal exige StackOS C3.')
key=Path('/usr/share/keyrings/stackos-archive-keyring.gpg')
if not key.is_file():raise SystemExit('Chave C3 instalada não encontrada.')
p=Path('/etc/apt/sources.list.d/stackos-c3.sources');p.parent.mkdir(parents=True,exist_ok=True)
p.write_text('Types: deb\nURIs: https://stackoslinux-dev.github.io/repo/c3/\nSuites: ./\nSigned-By: '+str(key)+'\n')
Path('/etc/apt/preferences.d/stackos-native-release').unlink(missing_ok=True)
Path('/etc/apt/preferences.d/stackos-c3-channel').write_text('Package: stackos-*\nPin: release o=StackOS,n=c3\nPin-Priority: 1001\n')
names=subprocess.check_output(['dpkg-query','-W','-f='+chr(36)+'{Package}\n','stackos-*'],text=True).splitlines()
if names:subprocess.run(['apt-mark','unhold',*names],check=True)
subprocess.run(['apt-get','update'],check=True)
print('Canal C3 assinado ativado. Abra Atualizações do StackOS.')
