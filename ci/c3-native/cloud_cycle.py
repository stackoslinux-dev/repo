#!/usr/bin/env python3
"""Single allowlisted native C3 testing lane; never writes the production c3 tree."""
import os,sys,json,hashlib,subprocess,urllib.request,urllib.error,tarfile,shutil,re,gzip,tempfile,datetime
from pathlib import Path
ROOT=Path('c3-root').resolve();OUT=Path('cycle-out');BASE='https://stackoslinux-dev.github.io/repo/c3/';TEST='https://raw.githubusercontent.com/stackoslinux-dev/repo/c3-testing/'
PKG='stackos-bugreport';MANIFEST='https://raw.githubusercontent.com/stackoslinux-dev/StackOS-Genesis/main/updates/testing/stackos-bugreport.json'
def run(*a,**kw):return subprocess.check_output(list(map(str,a)),text=True,**kw)
def download(url,limit=250_000_000):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'StackOS-C3-Native-Testing/1'}),timeout=90) as r:b=r.read(limit+1)
 if len(b)>limit:raise ValueError('Download limit: '+url)
 return b
def save(name,data):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data,indent=2)+'\n')
def read(name):return json.loads((OUT/name).read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def native(*args,**kw):return run('sudo','chroot',ROOT,'/usr/bin/env','PATH=/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL=C','DEBIAN_FRONTEND=noninteractive','SOURCE_DATE_EPOCH=1793923200',*args,**kw)
def decision(m,previous):
 assert m['package']==PKG and m['channel']=='c3-testing' and m['category']=='isolated-python-app'
 assert m['source_repository']=='stackoslinux-dev/StackOS-Genesis' and m['source_directory']=='apps/'+PKG
 assert re.fullmatch('[0-9a-f]{40}',m['source_commit']) and re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,99}',m['version'])
 assert m['automatic_testing_approved'] is True
 return subprocess.run(['dpkg','--compare-versions',m['version'],'gt',previous]).returncode==0
def detect():
 m=json.loads(download(MANIFEST,100000));previous='1.1.0+stackos1+c3.2+fix10.8'
 try:previous=json.loads(download(TEST+'state.json',100000))['version']
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
 changed=decision(m,previous);save('detection.json',{'manifest':m,'previous_version':previous,'update_available':changed,'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'official_source':MANIFEST})
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('changed='+str(changed).lower()+'\n')
 print(json.dumps(read('detection.json')),flush=True)
def bootstrap():
 seed=json.loads(Path('ci/c3-native/seed.json').read_text());archive=Path('native-seed.tar.xz')
 with archive.open('wb') as f:
  for p in sorted(Path('ci/c3-native/seed').glob('part-*')):f.write(p.read_bytes())
 assert digest(archive)==seed['archive_sha256']
 ROOT.mkdir(exist_ok=True);subprocess.run(['sudo','tar','-xJf',str(archive),'-C',str(ROOT)],check=True)
 for directory in ['etc/apt/sources.list.d','etc/apt/apt.conf.d','etc/apt/trusted.gpg.d','etc/ssl/certs','var/lib/dpkg/updates','var/lib/dpkg/info','var/lib/dpkg/triggers','var/lib/apt/lists/partial','var/cache/apt/archives/partial','var/log/apt','run/lock','run/dbus','tmp','proc','dev','root','work']:
  subprocess.run(['sudo','mkdir','-p',str(ROOT/directory)],check=True)
 for alias,target in [('bin','usr/bin'),('sbin','usr/sbin'),('lib','usr/lib')]:
  subprocess.run(['sudo','ln','-s',target,str(ROOT/alias)],check=True)
 subprocess.run(['sudo','chown',str(os.getuid())+':'+str(os.getgid()),str(ROOT/'work')],check=True)
 def write(name,data,mode='644'):
  p=Path(tempfile.mktemp());p.write_text(data);subprocess.run(['sudo','install','-m',mode,str(p),str(ROOT/name)],check=True);p.unlink()
 write('etc/passwd','root:x:0:0:root:/root:/bin/bash\n_apt:x:42:42::/nonexistent:/bin/false\n');write('etc/group','root:x:0:\n_apt:x:42:\n');write('etc/os-release','ID=stackos\nNAME="StackOS C3 CI"\nPRETTY_NAME="StackOS C3 native test client"\n');write('var/lib/dpkg/status','');write('etc/apt/apt.conf.d/99-ci','APT::Sandbox::User "root";\n');write('etc/resolv.conf',Path('/etc/resolv.conf').read_text())
 for d in ['dev','proc']:subprocess.run(['sudo','mount','--bind','/'+d,str(ROOT/d)],check=True)
 native('/usr/bin/python3','-c','import os,sys; assert sys.version_info[:2]==(3,13); assert os.confstr("CS_GNU_LIBC_VERSION")=="glibc 2.42"; print(sys.version,os.confstr("CS_GNU_LIBC_VERSION"))')
 # Independently pin the official bootstrap package hashes in reviewed code.
 baseline=json.loads(Path('ci/c3-native/baseline.json').read_text())
 for name in ['stackos-archive-keyring','stackos-c3-runtime','stackos-language-pack','stackos-display-support',PKG,'stackos-updater']:
  record=baseline[name];p=ROOT/'work'/record['file'];p.write_bytes(download(BASE+record['file']));assert digest(p)==record['sha256'];native('/usr/bin/dpkg','-i','/work/'+p.name)
 save('native-environment.json',{'status':'C3_NATIVE_PYTHON_GLIBC_DPKG_BOOTSTRAP_PASS','python':'3.13','glibc':'2.42','seed_sha256':seed['archive_sha256'],'owner_pc_or_ssd_required':False})
def test_engine(path):
 code='import runpy; d=runpy.run_path('+repr(path)+'); r=d["redact"]; assert "p4ssw0rd" not in r("https://alice:p4ssw0rd@localhost:8443/path",identities=[]); assert r("https://localhost/path",identities=[])=="https://localhost/path"; assert "ghp_demo12345" not in r("ghp_demo12345",identities=[]); d["validate_input"]("Problema real","Descrição"); print("BUGREPORT_PRIVACY_TESTS_PASS")'
 return native('/usr/bin/python3','-c',code)
def build():
 m=read('detection.json')['manifest'];assert decision(m,read('detection.json')['previous_version']);bootstrap()
 # Fetch the immutable official Git tree; the source commit is recorded in provenance.
 subprocess.run(['git','clone','--no-checkout','--filter=blob:none','https://github.com/'+m['source_repository']+'.git','source'],check=True)
 subprocess.run(['git','-C','source','checkout','--detach',m['source_commit']],check=True);assert run('git','-C','source','rev-parse','HEAD').strip()==m['source_commit']
 stage=ROOT/'work/package';shutil.copytree(Path('source')/m['source_directory'],stage,ignore=shutil.ignore_patterns('BINARY-BASELINE.json','__pycache__','md5sums'))
 control=(stage/'DEBIAN/control').read_text();assert 'Package: '+PKG+'\n' in control and 'Version: '+m['version']+'\n' in control and 'Architecture: all\n' in control
 assert not re.search(r'^(?:Pre-Depends|Conflicts|Breaks|Replaces|Essential|Protected):',control,re.M)
 for p in stage.rglob('*'):
  assert not p.is_symlink(),'symlinks require separate review';assert not(p.is_file() and p.open('rb').read(4)==b'\x7fELF'),'ELF not allowlisted in Python lane'
 for p in (stage/'usr/local/bin').glob('*'):p.chmod(0o755)
 for p in (stage/'DEBIAN').iterdir():p.chmod(0o755 if p.name in ['postinst','postrm','preinst','prerm'] else 0o644)
 test_engine('/work/package/usr/lib/stackos/bugreport/engine.py')
 native('/usr/bin/python3','-m','compileall','-q','-f','--invalidation-mode','checked-hash','-s','/work/package','-p','/','/work/package/usr')
 filename=PKG+'_'+m['version']+'_all.deb'
 for target in [filename,'repro.deb']:native('/usr/bin/dpkg-deb','--root-owner-group','-Zxz','--build','/work/package','/work/'+target)
 assert digest(ROOT/'work'/filename)==digest(ROOT/'work/repro.deb'),'non-reproducible DEB'
 native('/usr/bin/dpkg','-i','/work/'+filename);test_engine('/usr/lib/stackos/bugreport/engine.py');native('/usr/bin/apt-get','check');native('/usr/bin/dpkg','--audit')
 native('/usr/bin/dpkg','-r',PKG);assert not(ROOT/'usr/lib/stackos/bugreport/engine.py').exists();native('/usr/bin/dpkg','-i','/work/'+filename)
 OUT.mkdir(exist_ok=True);shutil.copy2(ROOT/'work'/filename,OUT/filename)
 save('build.json',{'status':'PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE','package':PKG,'version':m['version'],'filename':filename,'sha256':digest(OUT/filename),'source_commit':m['source_commit'],'source_engine_sha256':digest(stage/'usr/lib/stackos/bugreport/engine.py'),'native_environment':read('native-environment.json')})
def sign():
 b=read('build.json');assert b['status']=='PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE';assert digest(OUT/b['filename'])==b['sha256']
 key=os.environ.get('C3_TEST_SIGNING_KEY','');fingerprint=Path('ci/c3-native/testing-key.fpr').read_text().strip()
 if not key or not re.fullmatch('[0-9A-F]{40}',fingerprint):raise RuntimeError('Configure isolated C3_TEST_SIGNING_KEY and C3_TEST_SIGNING_FINGERPRINT secrets; production key is forbidden')
 assert fingerprint!='056F482818FF0BFCA93F31E28E5BDB912C8A2A16'
 channel=Path('testing-channel');channel.mkdir(exist_ok=True);shutil.copy2(OUT/b['filename'],channel/b['filename'])
 with tempfile.TemporaryDirectory() as home:
  os.chmod(home,0o700);subprocess.run(['gpg','--homedir',home,'--batch','--import'],input=key.encode(),check=True,stdout=subprocess.DEVNULL)
  fprs=run('gpg','--homedir',home,'--batch','--with-colons','--list-secret-keys').splitlines();assert fingerprint in [x.split(':')[9] for x in fprs if x.startswith('fpr:')]
  public=subprocess.check_output(['gpg','--homedir',home,'--batch','--export',fingerprint]);(channel/'testing-keyring.gpg').write_bytes(public)
  packages=run('dpkg-deb','-f',channel/b['filename'])+'Filename: '+b['filename']+'\nSize: '+str((channel/b['filename']).stat().st_size)+'\nSHA256: '+b['sha256']+'\n\n';(channel/'Packages').write_text(packages);(channel/'Packages.gz').write_bytes(gzip.compress(packages.encode(),mtime=0))
  now=datetime.datetime.now(datetime.timezone.utc);release='Origin: StackOS\nLabel: StackOS C3 Testing\nSuite: c3-testing\nCodename: c3\nArchitectures: all amd64\nDate: '+now.strftime('%a, %d %b %Y %H:%M:%S +0000')+'\nSHA256:\n'+''.join(' '+digest(channel/x)+' '+str((channel/x).stat().st_size)+' '+x+'\n' for x in ['Packages','Packages.gz']);(channel/'Release').write_text(release)
  for name,flags in [('InRelease',['--clearsign']),('Release.gpg',['--detach-sign'])]:subprocess.run(['gpg','--homedir',home,'--batch','--yes','--local-user',fingerprint,'--digest-algo','SHA256','--output',str(channel/name),*flags,str(channel/'Release')],check=True)
  subprocess.run(['gpg','--homedir',home,'--batch','--yes','--armor','--local-user',fingerprint,'--output',str(channel/(b['filename']+'.asc')),'--detach-sign',str(channel/b['filename'])],check=True)
  subprocess.run(['gpgv','--homedir',home,'--keyring',str((channel/'testing-keyring.gpg').resolve()),str(channel/'InRelease')],check=True)
 (channel/'state.json').write_text(json.dumps({**b,'signing_fingerprint':fingerprint,'channel':'c3-testing','run_url':os.environ.get('GITHUB_SERVER_URL','https://github.com')+'/'+os.environ.get('GITHUB_REPOSITORY','stackoslinux-dev/repo')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','local')},indent=2)+'\n')
 print('SIGNED_ISOLATED_TESTING_CHANNEL',fingerprint,flush=True)
def client():
 m=read('detection.json')['manifest'];bootstrap()
 expected=Path('ci/c3-native/testing-key.fpr').read_text().strip();key=download(TEST+'testing-keyring.gpg',100000)
 keyfile=ROOT/'work/testing-keyring.gpg';keyfile.write_bytes(key)
 listing=run('gpg','--batch','--with-colons','--show-keys',keyfile)
 assert expected in [x.split(':')[9] for x in listing.splitlines() if x.startswith('fpr:')]
 subprocess.run(['sudo','cp',str(keyfile),str(ROOT/'etc/apt/trusted.gpg.d/c3-testing.gpg')],check=True)
 source=ROOT/'work/testing.list';source.write_text('deb [signed-by=/etc/apt/trusted.gpg.d/c3-testing.gpg] '+TEST+' ./\n')
 subprocess.run(['sudo','cp',str(source),str(ROOT/'etc/apt/sources.list.d/c3-testing.list')],check=True)
 config=ROOT/'work/only-testing.conf';config.write_text('Dir::Etc::sourcelist "/etc/apt/sources.list.d/c3-testing.list";\nDir::Etc::sourceparts "-";\n')
 subprocess.run(['sudo','cp',str(config),str(ROOT/'etc/apt/apt.conf.d/99-only-testing')],check=True)
 native('/usr/bin/apt-get','update');native('/usr/bin/apt-get','check')
 shutil.copy2('ci/c3-native/updater_client.py',ROOT/'work/updater_client.py')
 subprocess.run(['sudo','chmod','1777',str(ROOT/'tmp')],check=True)
 subprocess.run(['sudo','mkdir','-p',str(ROOT/'tmp/.X11-unix')],check=True);subprocess.run(['sudo','mount','--bind','/tmp/.X11-unix',str(ROOT/'tmp/.X11-unix')],check=True)
 if Path('/run/dbus/system_bus_socket').exists():subprocess.run(['sudo','mount','--bind','/run/dbus',str(ROOT/'run/dbus')],check=True)
 proc=subprocess.Popen(['sudo','chroot',str(ROOT),'/usr/bin/env','PATH=/usr/sbin:/usr/bin:/sbin:/bin','DISPLAY=:99','GTK_A11Y=none','GSK_RENDERER=cairo','SHELL=/bin/bash','/usr/bin/python3','/work/updater_client.py',m['version']])
 import time
 captured=False
 while proc.poll() is None:
  if not captured and (ROOT/'work/updater-offered.json').exists():subprocess.run(['import','-display',':99','-window','root',str(OUT/'updater-offered.png')],check=True);captured=True
  time.sleep(.25)
 assert proc.returncode==0
 shutil.copy2(ROOT/'work/updater-final.json',OUT/'updater-final.json');assert read('updater-final.json')['status']=='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED'
 print(json.dumps(read('updater-final.json')),flush=True)
def selftest():
 m={'package':PKG,'channel':'c3-testing','category':'isolated-python-app','source_repository':'stackoslinux-dev/StackOS-Genesis','source_directory':'apps/'+PKG,'source_commit':'a'*40,'version':'1.1.1','automatic_testing_approved':True}
 assert decision(m,'1.1.0') and not decision(m,'1.1.1') and not decision(m,'1.1.2')
 for field,value in [('package','libc6'),('category','core-library'),('source_repository','foreign/repo'),('version','--unsafe')]:
  bad={**m,field:value}
  try:decision(bad,'1.0')
  except AssertionError:continue
  raise AssertionError('unsafe manifest accepted')
 print('POLICY_TESTS_PASS')
if __name__=='__main__':
 {'detect':detect,'build':build,'sign':sign,'client':client,'selftest':selftest}[sys.argv[1]]()
