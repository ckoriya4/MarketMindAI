from pathlib import Path
import shutil
root=Path.cwd();src=Path(__file__).resolve().parent/'frontend/src'
front=root/'frontend/src'
if not front.exists():front=root/'src'
app=front/'App.tsx'
if not app.exists():raise SystemExit('App.tsx not found. No files changed.')
a=app.read_text(encoding='utf-8')
import re
match=re.search(r'<b><Activity[^\n]+BACKEND ONLINE[^\n]+</b>',a)
if '<OIStatusNotification' not in a:
 if not match:raise SystemExit('Backend status bar not recognized. No files changed.')
 a=a[:match.end()]+'\n      <OIStatusNotification />'+a[match.end():]
 a='import OIStatusNotification from "./OIStatusNotification";\n'+a
p=front/'OISignalChart.tsx'
if not p.exists():raise SystemExit('Run from dashboard root: OISignalChart.tsx not found. No files changed.')
s=p.read_text(encoding='utf-8')
marker='    <div className="oi-heading">'
if '<OICrossoverAlerts' not in s:
 if marker not in s or 'setData' not in s:raise SystemExit('Unrecognized chart component; no files changed.')
 s='import OICrossoverAlerts from "./OICrossoverAlerts";\n'+s
 s=s.replace(marker,'    <OICrossoverAlerts data={data} error={!!error}/>\n'+marker,1)
backup=p.with_name(p.name+'.before-sum-alerts')
if not backup.exists():shutil.copy2(p,backup)
for f in src.iterdir():shutil.copy2(f,front/f.name)
p.write_text(s,encoding='utf-8')
print('Total OI crossover notifications added. Restart frontend, then click Enable OI crossover alerts. Backend and graph calculations unchanged.')

app_backup=app.with_name(app.name+'.before-oi-status-alerts')
if not app_backup.exists():shutil.copy2(app,app_backup)
app.write_text(a,encoding='utf-8')
print('Crossover notifications also installed inside BACKEND ONLINE status bar.')
