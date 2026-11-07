#!/usr/bin/env python3
"""Read official upstream versions. Unknown/critical native ABI groups fail closed."""
import json,re,urllib.request,urllib.parse,datetime,concurrent.futures,sys,html
from pathlib import Path
CATALOG=[
 {'component':'linux','installed':'7.2.13','url':'https://www.kernel.org/releases.json','kind':'kernel','group':'kernel/initramfs/firmware'},
 {'component':'mesa','installed':'24.3.4','url':'https://archive.mesa3d.org/','pattern':r'mesa-([0-9]+\.[0-9]+\.[0-9]+)\.tar\.xz','group':'mesa/llvm/vulkan/desktop'},
 {'component':'glibc','installed':'2.42','url':'https://ftp.gnu.org/gnu/glibc/','pattern':r'glibc-([0-9]+\.[0-9]+(?:\.[0-9]+)?)\.tar\.xz','group':'core-toolchain-ABI'},
 {'component':'linux-firmware','installed':'20261019','url':'https://cdn.kernel.org/pub/linux/kernel/firmware/','pattern':r'linux-firmware-([0-9]{8})\.tar\.xz','group':'kernel/firmware'},
 {'component':'glib','installed':'2.86.5','url':'https://download.gnome.org/sources/glib/','kind':'gnome','group':'GNOME/GTK/GLib'},
 {'component':'gtk','installed':'4.16.7','url':'https://download.gnome.org/sources/gtk/','kind':'gnome','group':'GNOME/GTK/GLib'},
 {'component':'gnome-shell','installed':None,'url':'https://download.gnome.org/sources/gnome-shell/','kind':'gnome','group':'GNOME/Mutter/graphics'},
 {'component':'mutter','installed':'50.6','url':'https://download.gnome.org/sources/mutter/','kind':'gnome','group':'GNOME/Mutter/graphics'},
 {'component':'llvm','installed':'19.1.7','url':'https://github.com/llvm/llvm-project/releases.atom','pattern':r'llvmorg-([0-9]+\.[0-9]+\.[0-9]+)(?=["<])','group':'LLVM/clang/mesa'},
 {'component':'NetworkManager','installed':'1.50.0','url':'https://gitlab.freedesktop.org/api/v4/projects/NetworkManager%2FNetworkManager/repository/tags?per_page=100','kind':'gitlab-tags','stable_even_minor':True,'group':'networking/dbus'},
 {'component':'pipewire','installed':'1.6.8','url':'https://gitlab.freedesktop.org/api/v4/projects/pipewire%2Fpipewire/repository/tags?per_page=100','kind':'gitlab-tags','stable_even_minor':True,'group':'audio/pipewire/alsa'},
 {'component':'alsa-lib','installed':'1.2.14','url':'https://www.alsa-project.org/files/pub/lib/','pattern':r'alsa-lib-([0-9]+\.[0-9]+\.[0-9]+)\.tar\.bz2','group':'audio/pipewire/alsa'},
 {'component':'python','installed':'3.13','url':'https://www.python.org/ftp/python/','kind':'python','pattern':r'href="(3\.[0-9]+\.[0-9]+)/"','group':'Python/extension-ABI'},
]
def fetch(url):
 assert urllib.parse.urlparse(url).scheme=='https'
 request=urllib.request.Request(url,headers={'User-Agent':'StackOS-C3-Component-Monitor/1'})
 with urllib.request.urlopen(request,timeout=25) as response:
  assert urllib.parse.urlparse(response.url).scheme=='https';data=response.read(4_000_001)
 assert len(data)<=4_000_000,'Official response too large'
 return data.decode('utf8')
def version_key(value):return tuple(map(int,value.split('.')))
def inspect(component):
 result={**component,'automatic_publication':False,'native_build_enabled':False,'reason':'Native recipe, ABI group tests and approval required before enabling this component'}
 try:
  document=fetch(component['url'])
  if component.get('kind')=='kernel':
   versions=[entry['version'] for entry in json.loads(document)['releases'] if re.fullmatch(r'[0-9]+(?:\.[0-9]+)+',entry['version']) and not entry.get('iseol',False)]
  elif component.get('kind')=='gitlab-tags':
   versions=[entry['name'] for entry in json.loads(document) if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',entry['name'])]
   if component.get('stable_even_minor'):versions=[value for value in versions if int(value.split('.')[1])%2==0]
  elif component.get('kind')=='gnome':
   series=re.findall(r'href="([0-9]+(?:\.[0-9]+)?)/"',document);series=[v for v in series if ('.' not in v and int(v)>=40) or ('.' in v and int(v.split('.')[-1])<90 and (int(v.split('.')[0])>=40 or int(v.split('.')[-1])%2==0))]
   assert series,'No stable series found';selected=max(series,key=version_key);directory=component['url']+selected+'/';listing=fetch(directory)
   versions=re.findall(re.escape(component['component'])+r'-([0-9]+\.[0-9]+(?:\.[0-9]+)?)\.tar\.xz',listing);versions=[v for v in versions if all(int(x)<90 for x in v.split('.')[1:])];result['release_directory']=directory
  elif component.get('kind')=='python':
   candidates=sorted(set(re.findall(component['pattern'],document)),key=version_key,reverse=True)
   versions=[]
   for candidate in candidates[:5]:
    directory=component['url']+candidate+'/'
    if re.search(r'href="Python-'+re.escape(candidate)+r'\.tar\.xz"',fetch(directory)):
     versions=[candidate];result['release_directory']=directory;break
  else:versions=re.findall(component['pattern'],document)
  assert versions,'No stable official version found';latest=max(versions,key=version_key);baseline=component.get('installed');result.update(latest_official=latest,state='BASELINE_NOT_REGISTERED' if baseline is None else 'UPDATE_REQUIRES_NATIVE_QUALIFICATION' if version_key(latest)>version_key(baseline) else 'NO_NEWER_OFFICIAL_VERSION')
 except Exception as error:result.update(state='SOURCE_CHECK_FAILED',error=str(error))
 return result
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(inspect,CATALOG))
 out=Path('cycle-out');out.mkdir(exist_ok=True);report={'checked_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'owner_pc_or_ssd_required':False,'coverage':'monitoring only for critical components; isolated BugReport app uses the separate native build lane','baseline_context':'C3 build provenance and SDK pkg-config Version snapshot 2026-11-06; target release manifest must be qualified before publishing critical components','components':results};(out/'component-monitor.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2));sys.exit(1 if all(row['state']=='SOURCE_CHECK_FAILED' for row in results) else 0)
