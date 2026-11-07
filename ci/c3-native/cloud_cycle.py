#!/usr/bin/env python3
"""Single allowlisted native C3 testing lane; never writes the production c3 tree."""
import os,sys,json,hashlib,subprocess,urllib.request,urllib.error,urllib.parse,tarfile,shutil,re,gzip,tempfile,datetime,contextlib,time
from pathlib import Path
ROOT=Path('c3-root').resolve();OUT=Path('cycle-out');BASE='https://stackoslinux-dev.github.io/repo/c3/';TEST='https://raw.githubusercontent.com/stackoslinux-dev/repo/c3-testing/'
PKG='stackos-bugreport';MANIFEST='https://raw.githubusercontent.com/stackoslinux-dev/StackOS-Genesis/main/updates/testing/stackos-bugreport.json'
def run(*a,**kw):return subprocess.check_output(list(map(str,a)),text=True,**kw)
def download(url,limit=250_000_000):
 for attempt in range(4):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'StackOS-C3-Native-Testing/1'}),timeout=30 if limit<=1_000_000 else 90) as response:data=response.read(limit+1)
   if len(data)>limit:raise ValueError('Download limit: '+url)
   return data
  except urllib.error.HTTPError as error:
   if error.code not in [429,500,502,503,504] or attempt==3:raise
   print('TRANSIENT_SOURCE_HTTP_RETRY',error.code,attempt+1,flush=True)
  except (urllib.error.URLError,TimeoutError,ConnectionError):
   if attempt==3:raise
   print('TRANSIENT_SOURCE_NETWORK_RETRY',attempt+1,flush=True)
  time.sleep(2**(attempt+1))
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
 assert int(m['version'].split(':')[-1].split('.')[0])<=m.get('max_major',1)
 return subprocess.run(['dpkg','--compare-versions',m['version'],'gt',previous]).returncode==0
def verify_signed_bytes(data,signature):
 with tempfile.TemporaryDirectory() as home:
  path=Path(home)/'data';path.write_bytes(data);sig=Path(home)/'data.asc';sig.write_bytes(signature)
  keyring=Path('ci/c3-native/testing-keyring.gpg').resolve()
  subprocess.run(['gpgv','--homedir',home,'--keyring',str(keyring),str(sig),str(path)],check=True,stdout=subprocess.DEVNULL)
 return json.loads(data)
def approved_state():
 # Resolve the channel once: marker and signature must come from one immutable commit.
 try:
  ref=json.loads(download('https://api.github.com/repos/stackoslinux-dev/repo/git/ref/heads/c3-testing',200000))
  snapshot=ref['object']['sha'];assert re.fullmatch('[0-9a-f]{40}',snapshot)
  base='https://raw.githubusercontent.com/stackoslinux-dev/repo/'+snapshot+'/'
  data=download(base+'validated.json',200000)
 except urllib.error.HTTPError as error:
  if error.code==404:return None
  raise
 state=verify_signed_bytes(data,download(base+'validated.json.asc',100000))
 assert state['package']==PKG and state['channel']=='c3-testing'
 assert state['validation_status']=='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED'
 assert state['status']=='PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE'
 assert state['signing_fingerprint']==Path('ci/c3-native/testing-key.fpr').read_text().strip()
 return state

def official_application_release():
 policy=json.loads(Path('ci/c3-native/tracking-policy.json').read_text())
 assert policy['package']==PKG and policy['source_repository']=='stackoslinux-dev/StackOS-Genesis' and policy['source_directory']=='apps/'+PKG and policy['ref']=='main'
 endpoint='https://api.github.com/repos/'+policy['source_repository']+'/commits?'+urllib.parse.urlencode({'path':policy['source_directory'],'sha':policy['ref'],'per_page':1})
 commits=json.loads(download(endpoint,500000));commit=commits[0]['sha'];assert re.fullmatch('[0-9a-f]{40}',commit)
 control_url='https://raw.githubusercontent.com/'+policy['source_repository']+'/'+commit+'/'+policy['source_directory']+'/DEBIAN/control'
 control=download(control_url,100000).decode('utf8');fields=dict(line.split(': ',1) for line in control.splitlines() if ': ' in line and not line[0].isspace())
 assert fields['Package']==PKG and fields['Architecture']=='all'
 return {**policy,'source_commit':commit,'version':fields['Version'],'official_version_source':control_url,'tracking_endpoint':endpoint}

def detect():
 m=official_application_release();approved=approved_state();previous=approved['version'] if approved else '1.1.0+stackos1+c3.2+fix10.8'
 changed=decision(m,previous);same=subprocess.run(['dpkg','--compare-versions',m['version'],'eq',previous]).returncode==0
 source_without_version_bump=bool(approved and same and approved['source_commit']!=m['source_commit'])
 now=datetime.datetime.now(datetime.timezone.utc);refresh=False
 if approved and same:
  signed=datetime.datetime.fromisoformat(approved['signed_utc'])
  refresh=(now-signed).total_seconds()>=86400
  if refresh:
   data=download(TEST+approved['filename']);assert hashlib.sha256(data).hexdigest()==approved['sha256']
   verify_signature=download(TEST+approved['filename']+'.asc',100000)
   with tempfile.TemporaryDirectory() as home:
    archive=Path(home)/'app.deb';archive.write_bytes(data);sig=Path(home)/'app.asc';sig.write_bytes(verify_signature)
    subprocess.run(['gpgv','--homedir',home,'--keyring',str(Path('ci/c3-native/testing-keyring.gpg').resolve()),str(sig),str(archive)],check=True)
   OUT.mkdir(exist_ok=True);(OUT/approved['filename']).write_bytes(data)
   fields=['status','package','version','filename','sha256','source_commit','source_engine_sha256','native_environment']
   save('build.json',{**{key:approved[key] for key in fields},'reused_validated_archive':True})
 save('detection.json',{'manifest':m,'previous_version':previous,'update_available':changed,'refresh_due':refresh,'checked_utc':now.isoformat(),'official_source':m['official_version_source'],'source_change_requires_version_bump':source_without_version_bump,'baseline':'signed Updater-validated marker' if approved else 'pinned native baseline','previous_client_validation':approved.get('validation_status') if approved else None})
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('changed='+str(changed).lower()+'\nrefresh='+str(refresh).lower()+'\n')
 print(json.dumps(read('detection.json')),flush=True)

def bootstrap():
 seed=json.loads(Path('ci/c3-native/seed.json').read_text());archive=Path('native-seed.tar.xz')
 with archive.open('wb') as f:
  for p in sorted(Path('ci/c3-native/seed').glob('part-*')):f.write(p.read_bytes())
 assert digest(archive)==seed['archive_sha256']
 ROOT.mkdir(exist_ok=True);subprocess.run(['sudo','tar','-xJf',str(archive),'-C',str(ROOT)],check=True)
 extra=json.loads(Path('ci/c3-native/extra.json').read_text());assert digest(Path('ci/c3-native/c3-utilities-extra.tar.xz'))==extra['sha256'];subprocess.run(['sudo','tar','-xJf','ci/c3-native/c3-utilities-extra.tar.xz','-C',str(ROOT)],check=True)
 for directory in ['etc/apt/sources.list.d','etc/apt/apt.conf.d','etc/apt/trusted.gpg.d','etc/ssl/certs','var/lib/dpkg/updates','var/lib/dpkg/info','var/lib/dpkg/triggers','var/lib/apt/lists/partial','var/cache/apt/archives/partial','var/log/apt','run/lock','run/dbus','tmp','proc','dev','root','work']:
  subprocess.run(['sudo','mkdir','-p',str(ROOT/directory)],check=True)
 for alias,target in [('bin','usr/bin'),('sbin','usr/sbin'),('lib','usr/lib')]:
  subprocess.run(['sudo','ln','-s',target,str(ROOT/alias)],check=True)
 subprocess.run(['sudo','chown',str(os.getuid())+':'+str(os.getgid()),str(ROOT/'work')],check=True)
 def write(name,data,mode='644'):
  p=Path(tempfile.mktemp());p.write_text(data);subprocess.run(['sudo','install','-m',mode,str(p),str(ROOT/name)],check=True);p.unlink()
 write('etc/passwd','root:x:0:0:root:/root:/bin/bash\n_apt:x:42:42::/nonexistent:/bin/false\n');write('etc/group','root:x:0:\n_apt:x:42:\n');write('etc/shells','/bin/bash\n/bin/sh\n/usr/bin/bash\n/usr/bin/sh\n');write('etc/os-release','ID=stackos\nNAME="StackOS C3 CI"\nPRETTY_NAME="StackOS C3 native test client"\n');write('var/lib/dpkg/status','');write('etc/apt/apt.conf.d/99-ci','APT::Sandbox::User "root";\nAcquire::https::CaInfo "/etc/ssl/certs/ca-certificates.crt";\n');write('etc/resolv.conf',Path('/etc/resolv.conf').read_text())
 for d in ['dev','proc']:subprocess.run(['sudo','mount','--bind','/'+d,str(ROOT/d)],check=True)
 native('/usr/bin/python3','-c','import os,sys; assert sys.version_info[:2]==(3,13); assert os.confstr("CS_GNU_LIBC_VERSION")=="glibc 2.42"; print(sys.version,os.confstr("CS_GNU_LIBC_VERSION"))')
 # Independently pin the official bootstrap package hashes in reviewed code.
 baseline=json.loads(Path('ci/c3-native/baseline.json').read_text())
 runtime=baseline['stackos-c3-runtime'];archive=ROOT/'work'/runtime['file'];archive.write_bytes(download(BASE+runtime['file']));assert digest(archive)==runtime['sha256']
 # Host dpkg-deb only extracts verified native C3 bytes; target execution remains chroot C3.
 subprocess.run(['sudo','dpkg-deb','--extract',str(archive),str(ROOT)],check=True)
 print(native('/usr/bin/python3','-c','import os,sys; print(sys.version); print(os.confstr("CS_GNU_LIBC_VERSION"))'),flush=True)
 for name in ['stackos-archive-keyring','stackos-c3-runtime','stackos-language-pack','stackos-display-support',PKG,'stackos-updater']:
  record=baseline[name];p=ROOT/'work'/record['file'];
  if not p.exists():p.write_bytes(download(BASE+record['file']))
  assert digest(p)==record['sha256'];print(native('/usr/bin/dpkg','-i','/work/'+p.name),flush=True)
 for method in ['https','http','store','gpgv']:
  print(native('/usr/lib/ld-linux-x86-64.so.2','--list','/usr/libexec/apt/methods/'+method),flush=True)
 save('native-environment.json',{'status':'C3_NATIVE_PYTHON_GLIBC_DPKG_BOOTSTRAP_PASS','python':'3.13','glibc':'2.42','seed_sha256':seed['archive_sha256'],'owner_pc_or_ssd_required':False})
def test_engine(path):
 code='import runpy; d=runpy.run_path('+repr(path)+'); r=d["redact"]; assert "p4ssw0rd" not in r("https://alice:p4ssw0rd@localhost:8443/path",identities=[]); assert r("https://localhost/path",identities=[])=="https://localhost/path"; assert "ghp_demo12345" not in r("ghp_demo12345",identities=[]); d["validate_input"]("Problema real","Descrição"); print("BUGREPORT_PRIVACY_TESTS_PASS")'
 return native('/usr/bin/python3','-c',code)
def build():
 m=read('detection.json')['manifest'];assert decision(m,read('detection.json')['previous_version']);bootstrap()
 # Fetch the immutable official Git tree; the source commit is recorded in provenance.
 subprocess.run(['git','clone','--no-checkout','--filter=blob:none','https://github.com/'+m['source_repository']+'.git','source'],check=True)
 subprocess.run(['git','-C','source','sparse-checkout','set',m['source_directory']],check=True)
 subprocess.run(['git','-C','source','checkout','--detach',m['source_commit']],check=True);assert run('git','-C','source','rev-parse','HEAD').strip()==m['source_commit']
 stage=ROOT/'work/package';shutil.copytree(Path('source')/m['source_directory'],stage,symlinks=True,ignore=shutil.ignore_patterns('BINARY-BASELINE.json','__pycache__','md5sums'))
 control=(stage/'DEBIAN/control').read_text();assert 'Package: '+PKG+'\n' in control and 'Version: '+m['version']+'\n' in control and 'Architecture: all\n' in control
 assert not re.search(r'^(?:Pre-Depends|Conflicts|Breaks|Replaces|Essential|Protected):',control,re.M)
 policy=json.loads(Path('ci/c3-native/tracking-policy.json').read_text())
 for p in stage.rglob('*'):
  assert not p.is_symlink(),'symlinks require separate review'
  if not p.is_file():continue
  relative=p.relative_to(stage).as_posix()
  assert p.open('rb').read(4)!=b'\x7fELF','ELF not allowlisted in Python lane'
  if relative=='DEBIAN/control':continue
  if relative.startswith('DEBIAN/'):
   assert p.name in policy['maintainer_scripts'] and digest(p)==policy['maintainer_scripts'][p.name],'maintainer script change requires review'
  else:assert relative in policy['allowed_files'] or any(relative.startswith(prefix) for prefix in policy['allowed_prefixes']),'file outside isolated app: '+relative
 for p in (stage/'usr/local/bin').glob('*'):p.chmod(0o755)
 for p in (stage/'DEBIAN').iterdir():p.chmod(0o755 if p.name in ['postinst','postrm','preinst','prerm'] else 0o644)
 test_engine('/work/package/usr/lib/stackos/bugreport/engine.py')
 native('/usr/bin/python3','-m','compileall','-q','-f','--invalidation-mode','checked-hash','-s','/work/package','-p','/','/work/package/usr')
 filename=PKG+'_'+m['version']+'_all.deb'
 for target in [filename,'repro.deb']:native('/usr/bin/dpkg-deb','--root-owner-group','-Zxz','--build','/work/package','/work/'+target)
 assert digest(ROOT/'work'/filename)==digest(ROOT/'work/repro.deb'),'non-reproducible DEB'
 native('/usr/bin/dpkg','-i','/work/'+filename);test_engine('/usr/lib/stackos/bugreport/engine.py');native('/usr/bin/apt-get','check');native('/usr/bin/dpkg','--audit')
 # Reject a genuinely incompatible variant of this real application; no synthetic package.
 original_control=(stage/'DEBIAN/control').read_text();bad_control=re.sub(r'^Depends:.*$',lambda m:m.group()+', libgtk-4-1 (>= 999)',original_control,flags=re.M);assert bad_control!=original_control
 (stage/'DEBIAN/control').write_text(bad_control);native('/usr/bin/dpkg-deb','--root-owner-group','-Zxz','--build','/work/package','/work/incompatible.deb');(stage/'DEBIAN/control').write_text(original_control)
 before=digest(ROOT/'var/lib/dpkg/status')
 try:native('/usr/bin/apt-get','--simulate','--no-install-recommends','install','/work/incompatible.deb',stderr=subprocess.STDOUT)
 except subprocess.CalledProcessError as error:
  assert error.returncode==100 and 'libgtk-4-1' in error.output;save('incompatible-block.json',{'status':'PASS_NATIVE_APT_BLOCKS_REAL_APP_INCOMPATIBLE_DEPENDENCY','returncode':error.returncode,'output':error.output,'status_unchanged':digest(ROOT/'var/lib/dpkg/status')==before});assert digest(ROOT/'var/lib/dpkg/status')==before
 else:raise AssertionError('incompatible candidate accepted')
 native('/usr/bin/dpkg','-r',PKG);assert not(ROOT/'usr/lib/stackos/bugreport/engine.py').exists();native('/usr/bin/dpkg','-i','/work/'+filename)
 OUT.mkdir(exist_ok=True);shutil.copy2(ROOT/'work'/filename,OUT/filename)
 save('build.json',{'status':'PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE','package':PKG,'version':m['version'],'filename':filename,'sha256':digest(OUT/filename),'source_commit':m['source_commit'],'source_engine_sha256':digest(stage/'usr/lib/stackos/bugreport/engine.py'),'native_environment':read('native-environment.json')})
@contextlib.contextmanager
def signing_key():
 key=os.environ.get('C3_TEST_SIGNING_KEY','');fingerprint=Path('ci/c3-native/testing-key.fpr').read_text().strip()
 if not key or not re.fullmatch('[0-9A-F]{40}',fingerprint):raise RuntimeError('Configure C3_TEST_SIGNING_KEY in this repository; production key is forbidden')
 assert fingerprint!='056F482818FF0BFCA93F31E28E5BDB912C8A2A16'
 with tempfile.TemporaryDirectory() as home:
  os.chmod(home,0o700);subprocess.run(['gpg','--homedir',home,'--batch','--import'],input=key.encode(),check=True,stdout=subprocess.DEVNULL)
  fprs=run('gpg','--homedir',home,'--batch','--with-colons','--list-secret-keys').splitlines();assert fingerprint in [line.split(':')[9] for line in fprs if line.startswith('fpr:')]
  yield home,fingerprint

def detach(home,fingerprint,path):
 subprocess.run(['gpg','--homedir',home,'--batch','--yes','--armor','--local-user',fingerprint,'--digest-algo','SHA256','--output',str(path)+'.asc','--detach-sign',str(path)],check=True)

def sign():
 b=read('build.json');assert b['status']=='PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE';assert digest(OUT/b['filename'])==b['sha256']
 channel=Path('testing-channel');channel.mkdir(exist_ok=True);shutil.copy2(OUT/b['filename'],channel/b['filename'])
 with signing_key() as (home,fingerprint):
  (channel/'testing-keyring.gpg').write_bytes(subprocess.check_output(['gpg','--homedir',home,'--batch','--export',fingerprint]))
  packages=run('dpkg-deb','-f',channel/b['filename']).rstrip()+'\nFilename: '+b['filename']+'\nSize: '+str((channel/b['filename']).stat().st_size)+'\nSHA256: '+b['sha256']+'\n\n'
  (channel/'Packages').write_text(packages);(channel/'Packages.gz').write_bytes(gzip.compress(packages.encode(),mtime=0))
  now=datetime.datetime.now(datetime.timezone.utc);expires=now+datetime.timedelta(days=7)
  release='Origin: StackOS\nLabel: StackOS C3 Testing\nSuite: c3-testing\nCodename: c3\nArchitectures: all amd64\nDate: '+now.strftime('%a, %d %b %Y %H:%M:%S +0000')+'\nValid-Until: '+expires.strftime('%a, %d %b %Y %H:%M:%S +0000')+'\nSHA256:\n'+''.join(' '+digest(channel/name)+' '+str((channel/name).stat().st_size)+' '+name+'\n' for name in ['Packages','Packages.gz'])
  (channel/'Release').write_text(release)
  for name,flags in [('InRelease',['--clearsign']),('Release.gpg',['--detach-sign'])]:subprocess.run(['gpg','--homedir',home,'--batch','--yes','--local-user',fingerprint,'--digest-algo','SHA256','--output',str(channel/name),*flags,str(channel/'Release')],check=True)
  detach(home,fingerprint,channel/b['filename'])
  state={**b,'signing_fingerprint':fingerprint,'channel':'c3-testing','signed_utc':now.isoformat(),'valid_until_utc':expires.isoformat(),'run_url':os.environ.get('GITHUB_SERVER_URL','https://github.com')+'/'+os.environ.get('GITHUB_REPOSITORY','stackoslinux-dev/repo')+'/actions/runs/'+os.environ.get('GITHUB_RUN_ID','local')}
  (channel/'state.json').write_text(json.dumps(state,indent=2)+'\n');detach(home,fingerprint,channel/'state.json')
  subprocess.run(['gpgv','--homedir',home,'--keyring',str((channel/'testing-keyring.gpg').resolve()),str(channel/'InRelease')],check=True)
 print('SIGNED_ISOLATED_TESTING_CHANNEL',fingerprint,flush=True)

def approve():
 channel=Path('testing-channel');state=json.loads((channel/'state.json').read_text());client=read('updater-final.json')
 assert client['status']=='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED'
 assert client['installed_version']==state['version'] and client['remaining_updates']==[]
 assert client['offered_updates']==[PKG] and digest(channel/state['filename'])==state['sha256']
 # A failed client never advances this signed marker, so the hourly detector retries.
 approved={**state,'validation_status':client['status'],'validated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'client':client}
 with signing_key() as (home,fingerprint):
  assert fingerprint==state['signing_fingerprint'];p=channel/'validated.json';p.write_text(json.dumps(approved,indent=2)+'\n');detach(home,fingerprint,p)
 print('REAL_UPDATER_VALIDATION_RECORDED',state['version'],flush=True)

def client():
 m=read('detection.json')['manifest'];bootstrap()
 snapshot=os.environ.get('C3_TEST_SNAPSHOT','');assert re.fullmatch('[0-9a-f]{40}',snapshot),'Published immutable testing commit required'
 client_base='https://raw.githubusercontent.com/stackoslinux-dev/repo/'+snapshot+'/'
 save('client-snapshot.json',{'commit':snapshot,'url':client_base,'production_channel':False})
 expected=Path('ci/c3-native/testing-key.fpr').read_text().strip();key=download(client_base+'testing-keyring.gpg',100000)
 keyfile=ROOT/'work/testing-keyring.gpg';keyfile.write_bytes(key)
 listing=run('gpg','--batch','--with-colons','--show-keys',keyfile)
 assert expected in [x.split(':')[9] for x in listing.splitlines() if x.startswith('fpr:')]
 subprocess.run(['sudo','cp',str(keyfile),str(ROOT/'etc/apt/trusted.gpg.d/c3-testing.gpg')],check=True)
 source=ROOT/'work/testing.list';source.write_text('deb [signed-by=/etc/apt/trusted.gpg.d/c3-testing.gpg] '+client_base+' ./\n')
 subprocess.run(['sudo','cp',str(source),str(ROOT/'etc/apt/sources.list.d/c3-testing.list')],check=True)
 config=ROOT/'work/only-testing.conf';config.write_text('Dir::Etc::sourcelist "/etc/apt/sources.list.d/c3-testing.list";\nDir::Etc::sourceparts "-";\n')
 subprocess.run(['sudo','cp',str(config),str(ROOT/'etc/apt/apt.conf.d/99-only-testing')],check=True)
 native('/usr/bin/apt-get','update');native('/usr/bin/apt-get','check')
 shutil.copy2('ci/c3-native/updater_client.py',ROOT/'work/updater_client.py')
 subprocess.run(['sudo','chmod','1777',str(ROOT/'tmp')],check=True)
 subprocess.run(['sudo','mkdir','-p',str(ROOT/'tmp/.X11-unix')],check=True);subprocess.run(['sudo','mount','--bind','/tmp/.X11-unix',str(ROOT/'tmp/.X11-unix')],check=True)
 if Path('/run/dbus/system_bus_socket').exists():subprocess.run(['sudo','mount','--bind','/run/dbus',str(ROOT/'run/dbus')],check=True)
 print(native('/usr/bin/env','SHELL=/bin/bash','/usr/bin/pkexec','/usr/bin/true'),flush=True)
 proc=subprocess.Popen(['sudo','chroot',str(ROOT),'/usr/bin/env','PATH=/usr/sbin:/usr/bin:/sbin:/bin','DISPLAY=:99','GTK_A11Y=none','GSK_RENDERER=cairo','SHELL=/bin/bash','HOME=/root','LC_ALL=C','/usr/bin/python3','/work/updater_client.py',m['version']])
 import time
 captured=False
 while proc.poll() is None:
  if not captured and (ROOT/'work/updater-offered.json').exists():subprocess.run(['import','-display',':99','-window','root',str(OUT/'updater-offered.png')],check=True);captured=True
  time.sleep(.25)
 if (ROOT/'work/updater-final.json').exists():shutil.copy2(ROOT/'work/updater-final.json',OUT/'updater-final.json')
 if (ROOT/'work/updater-offered.json').exists():shutil.copy2(ROOT/'work/updater-offered.json',OUT/'updater-offered.json')
 if (ROOT/'var/log/stackos-updater.log').exists():shutil.copy2(ROOT/'var/log/stackos-updater.log',OUT/'stackos-updater.log')
 for path in [ROOT/'root/.cache/stackos-updater/history.json']:
  if path.exists():shutil.copy2(path,OUT/'updater-history.json')
 assert proc.returncode==0,'Real Updater client failed; see preserved client evidence'
 assert read('updater-final.json')['status']=='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED'
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
 {'detect':detect,'build':build,'sign':sign,'client':client,'approve':approve,'selftest':selftest}[sys.argv[1]]()
