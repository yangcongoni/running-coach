"""Supervise the localhost training web server; no Garmin credentials required."""
from pathlib import Path
import ctypes,json,logging,logging.handlers,socket,subprocess,sys,time,urllib.request
ROOT=Path(__file__).resolve().parent
log=logging.getLogger('training-web');log.setLevel(logging.INFO)
handler=logging.handlers.RotatingFileHandler(ROOT/'web-watchdog.log',maxBytes=1048576,backupCount=3,encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));log.addHandler(handler)
# Prevent duplicate supervisors even if startup and timer triggers coincide.
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
kernel.CreateMutexW.restype=ctypes.c_void_p
mutex=kernel.CreateMutexW(None,False,'Local\\RunningCoachWebWatchdog')
if not mutex:raise ctypes.WinError(ctypes.get_last_error())
if ctypes.get_last_error()==183:sys.exit(0)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
def healthy():
 try:
  with opener.open('http://127.0.0.1:8765/api/health',timeout=5) as r:
   return r.status==200 and json.load(r).get('status')=='ok'
 except Exception:return False
def occupied():
 with socket.socket() as s:
  s.settimeout(2)
  return s.connect_ex(('127.0.0.1',8765))==0
child=None;failures=0;stream=None
log.info('Supervisor started pid=%s',__import__('os').getpid())
while True:
 if healthy():
  failures=0
 else:
  failures+=1
  if child is not None and child.poll() is not None:
   log.warning('Server exited code=%s',child.returncode);child=None
  if child is not None and failures>=3:
   log.warning('Server unhealthy on 3 checks; restarting owned process pid=%s',child.pid)
   subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
   child.wait(timeout=15);child=None
  if child is None and not occupied():
   if stream:stream.close()
   stream=open(ROOT/'web-managed-server.log','ab',buffering=0)
   child=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'server.py')],cwd=ROOT,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW)
   log.info('Started server pid=%s',child.pid);failures=0
  elif child is None and failures in (1,3):
   log.error('Port occupied by an unowned/unhealthy service; will not terminate unrelated process')
 time.sleep(10)
