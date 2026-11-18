"""Run from existing dashboard root with backend/frontend stopped."""
from pathlib import Path
import re,shutil
root=Path.cwd();front=root/'frontend/src'
if not front.exists():front=root/'src'
updates={}
def load(p):
 if not p.exists():raise SystemExit(f'Required file missing: {p}. No files changed.')
 return p.read_text(encoding='utf-8')
p=root/'backend/services/session_recorder.py';s=load(p)
old="            try:interval=max(5,float(os.getenv('OI_COLLECT_INTERVAL_SECONDS','5')))\n            except ValueError:interval=5\n            self.stop_event.wait(interval)"
new="            self.stop_event.wait(max(0.1,3-(time.monotonic()-refresh_started))) # 3s refresh target"
if 'refresh_started = time.monotonic()' not in s:
 if old not in s or '        while not self.stop_event.is_set():\n' not in s:raise SystemExit('Recorder version not recognized. No files changed.')
 s=s.replace('        while not self.stop_event.is_set():\n','        while not self.stop_event.is_set():\n            refresh_started = time.monotonic()\n',1).replace(old,new)
updates[p]=s
for name,oldttl in [('trade_setups.py',10),('option_chain.py',5),('chart_service.py',5)]:
 p=root/'backend/services'/name;s=load(p)
 # Only short response cache TTLs, never indicator periods/history caches.
 pattern=rf'(time\.monotonic\(\)-\w+\[0\]\s*<){oldttl}(?=\s*:)'
 s,count=re.subn(pattern,lambda m:m[1]+'3',s)
 if not count and not re.search(r'time\.monotonic\(\)-\w+\[0\]\s*<3\s*:',s):raise SystemExit(f'Cache version not recognized: {name}. No files changed.')
 updates[p]=s
for name in ('TradeSetupPanel.tsx','OISignalChart.tsx'):
 p=front/name;s=load(p)
 if 'const refreshStarted=performance.now();' not in s:
  match=re.search(r'const load=async\(\)=>\s*\{',s)
  if not match:raise SystemExit(f'Polling function not found: {name}. No files changed.')
  s=s[:match.end()]+'const refreshStarted=performance.now();'+s[match.end():]
  s,count=re.subn(r'setTimeout\(load,(?:10000|3000)\)', 'setTimeout(load,Math.max(100,3000-(performance.now()-refreshStarted)))',s)
  if count!=1:raise SystemExit(f'Polling interval not recognized: {name}. No files changed.')
 updates[p]=s
for p,s in updates.items():
 if p.suffix=='.py':compile(s,str(p),'exec')
for p,s in updates.items():
 b=p.with_name(p.name+'.before-3s-refresh')
 if not b.exists():shutil.copy2(p,b)
 p.write_text(s,encoding='utf-8')
print('3-second target cadence installed: collector, OI graph, setup cards; response caches capped at 3s. Restart backend and frontend. No overlapping requests.')
