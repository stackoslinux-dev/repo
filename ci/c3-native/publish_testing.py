#!/usr/bin/env python3
"""Atomic publication in the isolated testing branch; production is never written."""
import urllib.request,urllib.error,json,os,base64,sys,hashlib,subprocess,tempfile
from pathlib import Path
REPO='stackoslinux-dev/repo';BRANCH='c3-testing';BASE='https://api.github.com/repos/'+REPO
TOKEN=os.environ['GH_TOKEN']
def api(path,data=None,method=None):
 req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'StackOS-C3-Testing-Publisher'},method=method)
 with urllib.request.urlopen(req,timeout=45) as response:return json.load(response)
channel=Path('testing-channel');state=json.loads((channel/'state.json').read_text());expected=Path('ci/c3-native/testing-key.fpr').read_text().strip()
assert state['status']=='PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE' and state['package']=='stackos-bugreport' and state['channel']==BRANCH
assert state['signing_fingerprint']==expected
with tempfile.TemporaryDirectory() as home:
 for name in ['state.json',state['filename']]:
  subprocess.run(['gpgv','--homedir',home,'--keyring',str(Path('ci/c3-native/testing-keyring.gpg').resolve()),str(channel/(name+'.asc')),str(channel/name)],check=True)
 if '--approved' in sys.argv:
  approved=json.loads((channel/'validated.json').read_text());assert approved['validation_status']=='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED';assert approved['version']==state['version'] and approved['sha256']==state['sha256']
  subprocess.run(['gpgv','--homedir',home,'--keyring',str(Path('ci/c3-native/testing-keyring.gpg').resolve()),str(channel/'validated.json.asc'),str(channel/'validated.json')],check=True)
assert hashlib.sha256((channel/state['filename']).read_bytes()).hexdigest()==state['sha256']
allowed={'testing-keyring.gpg','Packages','Packages.gz','Release','Release.gpg','InRelease','state.json','state.json.asc',state['filename'],state['filename']+'.asc'}
if '--approved' in sys.argv:allowed|={'validated.json','validated.json.asc'}
try:head=api('/git/ref/heads/'+BRANCH)['object']['sha'];tree=api('/git/commits/'+head)['tree']['sha']
except urllib.error.HTTPError as error:
 if error.code!=404:raise
 head=None;tree=None
entries=[]
for path in sorted(channel.iterdir()):
 assert path.is_file() and not path.is_symlink() and path.name in allowed,path.name
 blob=api('/git/blobs',{'encoding':'base64','content':base64.b64encode(path.read_bytes()).decode()})['sha'];entries.append({'path':path.name,'mode':'100644','type':'blob','sha':blob})
payload={'tree':entries}
if tree:payload['base_tree']=tree  # Retain previous package files for clients holding older indexes.
newtree=api('/git/trees',payload)['sha'];commit=api('/git/commits',{'tree':newtree,'parents':[head] if head else [],'message':('Validated' if '--approved' in sys.argv else 'Candidate')+' C3 testing: '+state['package']+' '+state['version']})['sha']
if head:api('/git/refs/heads/'+BRANCH,{'sha':commit,'force':False},'PATCH')
else:api('/git/refs',{'ref':'refs/heads/'+BRANCH,'sha':commit})
print(json.dumps({'status':'VALIDATED_TESTING_UPDATE_PUBLISHED' if '--approved' in sys.argv else 'SIGNED_TESTING_CANDIDATE_PUBLISHED','commit':commit,'channel':'https://raw.githubusercontent.com/'+REPO+'/'+BRANCH+'/','production_modified':False}))

if os.environ.get('GITHUB_OUTPUT'):
 with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('commit='+commit+'\n')
