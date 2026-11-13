#!/usr/bin/env python3
"""Isolated ABI7 testing channel inside the existing C3 updates workflow."""
from pathlib import Path
import sys,os,json,re,hashlib,subprocess,shutil,gzip,datetime,tempfile,urllib.request,urllib.error,base64
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import cloud_cycle as c3
OUT=Path('compat-out');CHANNEL=Path('compat-channel');PREFIX='compat/libvpx7/';REPO='stackoslinux-dev/repo';BRANCH='c3-testing'
PASS='PASS_NATIVE_C3_REPRODUCIBLE_LIBVPX7_CODEC_AND_DEB';CLIENT='PASS_NATIVE_C3_SIGNED_APT_CODEC_INSTALL'
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_text())
def check_state(s):
 assert s['status']==PASS and s['package']=='libvpx7' and s['soname']=='libvpx.so.7'
 assert s['replacement_of_existing_abi11'] is False and s['native_binary_rebuild_reproducible'] is True
 assert re.fullmatch(r'libvpx7_[A-Za-z0-9.+~_-]+_amd64.deb',s['filename'])
 assert re.fullmatch(r'[0-9a-f]{64}',s['sha256'])
 assert re.fullmatch(r'libvpx\.so\.7\.[0-9.]+',s['library_file'])
def verify(path):
 subprocess.run(['gpgv','--keyring',str(Path('ci/c3-native/testing-keyring.gpg').resolve()),str(path)+'.asc',str(path)],check=True)
def sign():
 s=read(OUT/'build.json');check_state(s);assert sha(OUT/s['filename'])==s['sha256']
 CHANNEL.mkdir(exist_ok=True)
 for n in [s['filename'],'vpxenc','vpxdec','vector.yuv']:shutil.copy2(OUT/n,CHANNEL/n)
 s['qualification_tools']={n:sha(CHANNEL/n) for n in ['vpxenc','vpxdec','vector.yuv']}
 with c3.signing_key() as (home,fpr):
  s.update(signing_fingerprint=fpr,channel=BRANCH,channel_subdirectory=PREFIX,signed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
  (CHANNEL/'testing-keyring.gpg').write_bytes(subprocess.check_output(['gpg','--homedir',home,'--batch','--export',fpr]))
  packages=subprocess.check_output(['dpkg-deb','-f',str(CHANNEL/s['filename'])],text=True).rstrip()+'\nFilename: '+s['filename']+'\nSize: '+str((CHANNEL/s['filename']).stat().st_size)+'\nSHA256: '+s['sha256']+'\n\n'
  (CHANNEL/'Packages').write_text(packages);(CHANNEL/'Packages.gz').write_bytes(gzip.compress(packages.encode(),mtime=0))
  now=datetime.datetime.now(datetime.timezone.utc);expires=now+datetime.timedelta(days=7)
  release='Origin: StackOS\nLabel: StackOS C3 ABI7 Testing\nSuite: c3-testing\nCodename: c3\nArchitectures: amd64\nDate: '+now.strftime('%a, %d %b %Y %H:%M:%S +0000')+'\nValid-Until: '+expires.strftime('%a, %d %b %Y %H:%M:%S +0000')+'\nSHA256:\n'+''.join(' '+sha(CHANNEL/n)+' '+str((CHANNEL/n).stat().st_size)+' '+n+'\n' for n in ['Packages','Packages.gz'])
  (CHANNEL/'Release').write_text(release)
  for name,flag in [('InRelease','--clearsign'),('Release.gpg','--detach-sign')]:subprocess.run(['gpg','--homedir',home,'--batch','--yes','--local-user',fpr,'--digest-algo','SHA256','--output',str(CHANNEL/name),flag,str(CHANNEL/'Release')],check=True)
  for name in [s['filename'],'vpxenc','vpxdec','vector.yuv']:c3.detach(home,fpr,CHANNEL/name)
  (CHANNEL/'state.json').write_text(json.dumps(s,indent=2)+'\n');c3.detach(home,fpr,CHANNEL/'state.json')
 print('SIGNED_NATIVE_CODEC_TESTING_ONLY',flush=True)
def client():
 commit=os.environ['C3_TEST_SNAPSHOT'];assert re.fullmatch('[0-9a-f]{40}',commit)
 base='https://raw.githubusercontent.com/'+REPO+'/'+commit+'/'+PREFIX
 s=c3.verify_signed_bytes(c3.download(base+'state.json',500000),c3.download(base+'state.json.asc',100000));check_state(s)
 assert s['channel']==BRANCH and s['channel_subdirectory']==PREFIX
 OUT.mkdir(exist_ok=True);c3.bootstrap();root=c3.ROOT
 key=Path('ci/c3-native/testing-keyring.gpg');subprocess.run(['sudo','install','-m','644',str(key),str(root/'usr/share/keyrings/stackos-testing.gpg')],check=True)
 source=root/'work/codec-testing.sources';source.write_text('Types: deb\nURIs: '+base+'\nSuites: ./\nSigned-By: /usr/share/keyrings/stackos-testing.gpg\n')
 c3.native('/usr/bin/cp','/work/codec-testing.sources','/etc/apt/sources.list.d/codec-testing.sources')
 # Seed packages may carry an old offline bootstrap source. This disposable
 # client must use only the immutable signed HTTPS snapshot under test.
 removed=[]
 for p in (root/'etc/apt/sources.list.d').iterdir():
  if p.name!='codec-testing.sources' and p.suffix in ['.list','.sources']:
   removed.append({'file':p.name,'content':p.read_text()});c3.native('/usr/bin/rm','-f','/etc/apt/sources.list.d/'+p.name)
 empty=root/'work/empty-sources.list';empty.write_text('')
 c3.native('/usr/bin/cp','/work/empty-sources.list','/etc/apt/sources.list')
 (OUT/'bootstrap-sources-replaced.json').write_text(json.dumps({'scope':'Disposable native CI root only; ISO and production untouched','removed':removed,'only_active_uri':base},indent=2)+'\n')
 assert [p.name for p in (root/'etc/apt/sources.list.d').iterdir() if p.suffix in ['.list','.sources']]==['codec-testing.sources']
 config=root/'work/codec-only.conf';config.write_text('Dir::Etc::sourcelist \"/etc/apt/sources.list.d/codec-testing.sources\";\nDir::Etc::sourceparts \"-\";\n')
 c3.native('/usr/bin/cp','/work/codec-only.conf','/etc/apt/apt.conf.d/99-codec-only')
 out=c3.native('/usr/bin/apt-get','update');(OUT/'signed-apt-update.log').write_text(out)
 assert 'InRelease' in out and 'Packages' in out
 policy=c3.native('/usr/bin/apt-cache','policy','libvpx7');(OUT/'apt-policy.log').write_text(policy);assert s['version'] in policy
 previous=read(OUT/'detection.json').get('previous')
 actual_upgrade=False
 if previous:
  check_state(previous);assert previous['client_status']==CLIENT
  old_commit=previous['client']['publication_commit'];assert re.fullmatch('[0-9a-f]{40}',old_commit)
  old_base='https://raw.githubusercontent.com/'+REPO+'/'+old_commit+'/'+PREFIX
  old=root/'work'/previous['filename'];old.write_bytes(c3.download(old_base+previous['filename']))
  assert sha(old)==previous['sha256']
  sig=OUT/'previous-native-codec.asc';sig.write_bytes(c3.download(old_base+previous['filename']+'.asc',100000))
  subprocess.run(['gpgv','--keyring',str(key.resolve()),str(sig),str(old)],check=True)
  c3.native('/usr/bin/dpkg','-i','/work/'+old.name)
  order=subprocess.run(['dpkg','--compare-versions',s['version'],'gt',previous['version']]).returncode
  assert order in (0,1)
  assert subprocess.run(['dpkg','--compare-versions',s['version'],'ge',previous['version']]).returncode==0,'No downgrade'
  actual_upgrade=order==0
 # Genuine older releases are used only when previously signed and client
 # validated. Initial rollout is honestly classified as a first install.
 before=subprocess.run(['sudo','chroot',str(root),'/usr/bin/dpkg-query','-W','-f=${db:Status-Status}','libvpx7'],capture_output=True,text=True)
 if previous:assert before.returncode==0 and before.stdout.strip()=='installed'
 else:assert before.returncode!=0 or before.stdout.strip()!='installed'
 if actual_upgrade:
  offered=json.loads(c3.native('/usr/lib/stackos/stackos-updater-helper','check'))
  assert [p['name'] for p in offered['packages']]==['libvpx7']
  (OUT/'actual-updater-offered.json').write_text(json.dumps(offered,indent=2)+'\n')
  install=c3.native('/usr/lib/stackos/stackos-updater-helper','install')
 else:
  install=c3.native('/usr/bin/apt-get','install','-y','--no-install-recommends','libvpx7='+s['version'])
 (OUT/'apt-install.log').write_text(install)
 assert c3.native('/usr/bin/dpkg-query','-W','-f=${Version}','libvpx7')==s['version']
 assert not c3.native('/usr/bin/dpkg','-V','libvpx7').strip();c3.native('/usr/bin/apt-get','check')
 assert sha(root/'usr/lib'/s['library_file'])==s['library_sha256']
 for name,digest in s['qualification_tools'].items():
  data=c3.download(base+name);assert hashlib.sha256(data).hexdigest()==digest
  p=root/'work'/name;p.write_bytes(data)
  sig=c3.download(base+name+'.asc',100000);(OUT/(name+'.asc')).write_bytes(sig)
  subprocess.run(['gpgv','--keyring',str(key.resolve()),str(OUT/(name+'.asc')),str(p)],check=True)
  if name!='vector.yuv':c3.native('/usr/bin/chmod','755','/work/'+name)
 c3.native('/usr/bin/env','LD_LIBRARY_PATH=/usr/lib','/work/vpxenc','--codec=vp9','--i420','--lossless=1','--threads=1','--width=32','--height=32','--fps=30/1','--limit=4','--ivf','-o','/work/client.ivf','/work/vector.yuv')
 c3.native('/usr/bin/env','LD_LIBRARY_PATH=/usr/lib','/work/vpxdec','--codec=vp9','--rawvideo','--i420','-o','/work/client.yuv','/work/client.ivf')
 assert (root/'work/client.yuv').read_bytes()==(root/'work/vector.yuv').read_bytes()
 result={'status':CLIENT,'package':'libvpx7','installed_version':s['version'],'sha256':s['sha256'],'library_sha256':s['library_sha256'],'publication_commit':commit,'native_bootstrap':True,'signed_https_apt_install':True,'full_simd_lossless_roundtrip':True,'first_install_not_updater_upgrade':previous is None,'actual_updater_upgrade':actual_upgrade,'refresh_without_downgrade':bool(previous and not actual_upgrade),'production_modified':False,'owner_pc_or_ssd_required':False}
 (OUT/'client.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
def approve():
 s=read(CHANNEL/'state.json');check_state(s);verify(CHANNEL/'state.json');c=read(OUT/'client.json')
 assert c['status']==CLIENT and c['installed_version']==s['version'] and c['sha256']==s['sha256']
 s.update(client_status=CLIENT,client=c,validated_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
 with c3.signing_key() as (home,fpr):
  assert fpr==s['signing_fingerprint'];p=CHANNEL/'validated.json';p.write_text(json.dumps(s,indent=2)+'\n');c3.detach(home,fpr,p)
def publish():
 s=read(CHANNEL/'state.json');check_state(s);verify(CHANNEL/'state.json');verify(CHANNEL/s['filename']);assert sha(CHANNEL/s['filename'])==s['sha256']
 assert s['channel']==BRANCH and s['channel_subdirectory']==PREFIX
 assert s['signing_fingerprint']==Path('ci/c3-native/testing-key.fpr').read_text().strip()
 allowed={'state.json','state.json.asc','testing-keyring.gpg','Packages','Packages.gz','Release','Release.gpg','InRelease',s['filename'],s['filename']+'.asc','vpxenc','vpxenc.asc','vpxdec','vpxdec.asc','vector.yuv','vector.yuv.asc'}
 if '--approved' in sys.argv:
  v=read(CHANNEL/'validated.json');verify(CHANNEL/'validated.json');assert v['client_status']==CLIENT and v['sha256']==s['sha256'];allowed|={'validated.json','validated.json.asc'}
 token=os.environ['GH_TOKEN']
 def api(path,data=None,method=None):
  req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'StackOS-C3-native-codec'},method=method)
  with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
 head=api('/git/ref/heads/'+BRANCH)['object']['sha'];tree=api('/git/commits/'+head)['tree']['sha'];entries=[]
 for p in sorted(CHANNEL.iterdir()):
  assert p.is_file() and not p.is_symlink() and p.name in allowed
  blob=api('/git/blobs',{'encoding':'base64','content':base64.b64encode(p.read_bytes()).decode()})['sha'];entries.append({'path':PREFIX+p.name,'mode':'100644','type':'blob','sha':blob})
 tree=api('/git/trees',{'base_tree':tree,'tree':entries})['sha'];commit=api('/git/commits',{'tree':tree,'parents':[head],'message':'C3 ABI7 testing '+('validated: ' if '--approved' in sys.argv else 'candidate: ')+s['version']})['sha']
 api('/git/refs/heads/'+BRANCH,{'sha':commit,'force':False},'PATCH')
 print(json.dumps({'testing_commit':commit,'subdirectory':PREFIX,'production_modified':False}))
 if os.environ.get('GITHUB_OUTPUT'):
  with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('commit='+commit+'\n')
if __name__=='__main__':
 assert len(sys.argv)>1 and sys.argv[1] in ['sign','client','approve','publish']
 {'sign':sign,'client':client,'approve':approve,'publish':publish}[sys.argv[1]]()
