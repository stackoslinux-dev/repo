#!/usr/bin/env python3
"""Publish only the isolated branch, atomically; no production writes."""
import urllib.request,urllib.error,json,os,base64
from pathlib import Path
REPO='stackoslinux-dev/repo';BRANCH='c3-testing';BASE='https://api.github.com/repos/'+REPO
TOKEN=os.environ['GH_TOKEN']
def api(path,data=None,method=None):
 req=urllib.request.Request(BASE+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+TOKEN,'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'StackOS-C3-Testing-Publisher'},method=method)
 with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
channel=Path('testing-channel');state=json.loads((channel/'state.json').read_text());assert state['status']=='PASS_NATIVE_REPRODUCIBLE_REAL_APP_INSTALL_REMOVE' and state['package']=='stackos-bugreport' and state['channel']==BRANCH
try:head=api('/git/ref/heads/'+BRANCH)['object']['sha'];tree=api('/git/commits/'+head)['tree']['sha']
except urllib.error.HTTPError as e:
 if e.code!=404:raise
 head=None;tree=None
entries=[]
for p in sorted(channel.iterdir()):
 assert p.is_file() and not p.is_symlink() and p.name not in ['.git','private.key']
 blob=api('/git/blobs',{'encoding':'base64','content':base64.b64encode(p.read_bytes()).decode()})['sha'];entries.append({'path':p.name,'mode':'100644','type':'blob','sha':blob})
payload={'tree':entries}
if tree:payload['base_tree']=tree
newtree=api('/git/trees',payload)['sha'];commit=api('/git/commits',{'tree':newtree,'parents':[head] if head else [],'message':'C3 testing: '+state['package']+' '+state['version']})['sha']
if head:api('/git/refs/heads/'+BRANCH,{'sha':commit,'force':False},'PATCH')
else:api('/git/refs',{'ref':'refs/heads/'+BRANCH,'sha':commit})
print(json.dumps({'status':'PUBLISHED_TESTING_ONLY','commit':commit,'channel':'https://raw.githubusercontent.com/'+REPO+'/'+BRANCH+'/','production_modified':False}))
