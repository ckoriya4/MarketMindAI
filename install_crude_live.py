"""Run from project root after copying supplied backend/frontend files."""
from pathlib import Path
import re
main=Path('backend/main.py');app=Path('frontend/src/App.tsx')
if not app.exists():app=Path('src/App.tsx')
s=main.read_text(encoding='utf-8');a=app.read_text(encoding='utf-8')
marker='app.include_router(live_crude_router)'
if marker not in s:
    insert='\nfrom .services.live_crude import router as live_crude_router\napp.include_router(live_crude_router)\n\n'
    pos=s.find('if __name__');s=s[:pos]+insert+s[pos:] if pos>=0 else s+insert
if 'import CrudeOilPanel from "./LiveCrudeOilPanel"' not in a:
    pattern=r'import\s*\{([^}]+)\}\s*from\s*[\'"]\./EnergyPanels[\'"];?'
    match=re.search(pattern,a)
    if not match or 'CrudeOilPanel' not in match.group(1):raise SystemExit('Could not locate CrudeOilPanel import. Manually import the default from ./LiveCrudeOilPanel; keep OfficialNewsPanel from ./EnergyPanels.')
    names=[n.strip() for n in match.group(1).split(',') if n.strip()!='CrudeOilPanel']
    replacement=('import { '+', '.join(names)+' } from "./EnergyPanels";\n' if names else '')+'import CrudeOilPanel from "./LiveCrudeOilPanel";'
    a=a[:match.start()]+replacement+a[match.end():]
for path,text in [(main,s),(app,a)]:
    backup=path.with_name(path.name+'.before-crude-live')
    if not backup.exists():backup.write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
    path.write_text(text,encoding='utf-8')
print('MCX live routes and panel installed. Restart backend and Vite. Existing news routes preserved.')
