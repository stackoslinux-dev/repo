from pathlib import Path
import sys,time,json,subprocess
sys.path.insert(0,'/usr/lib/stackos/updater-ui')
from modern_updater import Updater,GLib
package='stackos-bugreport';expected=sys.argv[1];app=Updater();state={'phase':'window','started':time.monotonic()}
def poll():
 try:
  if time.monotonic()-state['started']>240:raise TimeoutError(str(state))
  phase=state['phase'];print('REAL_APP_UPDATER_PHASE',phase,flush=True)
  if phase=='window' and app.window and not app.busy:app.check_button.emit('clicked');state['phase']='checking'
  elif phase=='checking' and not app.busy:
   names=[p['name'] for p in app.updates];assert names==[package],(names,app.current_data);state['offered_updates']=names;state['offered_at']=time.monotonic();Path('/work/updater-offered.json').write_text(json.dumps(state));state['phase']='offered'
  elif phase=='offered' and time.monotonic()-state['offered_at']>8:app.install_button.emit('clicked');state['phase']='installing'
  elif phase=='installing' and not app.busy:
   version=subprocess.check_output(['dpkg-query','-W','-f=${Version}',package],text=True);assert version==expected,(version,expected);assert not app.updates,app.current_data
   import runpy
   engine=runpy.run_path('/usr/lib/stackos/bugreport/engine.py');assert 'p4ssw0rd' not in engine['redact']('https://alice:p4ssw0rd@localhost:8443/path',identities=[])
   state.update(status='PASS_REAL_STACKOS_UPDATER_DETECTED_AND_INSTALLED',installed_version=version,remaining_updates=app.updates);Path('/work/updater-final.json').write_text(json.dumps(state,indent=2));app.quit();return False
  return True
 except Exception as error:
  state.update(status='FAILED',error=str(error));Path('/work/updater-final.json').write_text(json.dumps(state,indent=2));print(json.dumps(state),flush=True);app.quit();return False
GLib.timeout_add(1000,poll)
app.run(['stackos-updater-ci'])
raise SystemExit(0 if state.get('status','').startswith('PASS_') else 1)
