"""Run with backend stopped, from dashboard project root. Backups are kept."""
from pathlib import Path
import shutil,re
source=Path(__file__).resolve().parent
root=Path.cwd()
main=root/'backend/main.py'
frontend=root/'frontend/src'
if not frontend.exists():frontend=root/'src'
if not main.exists() or not (frontend/'TradeSetupPanel.tsx').exists():
    raise SystemExit('Run from the existing dashboard root with backend/main.py and TradeSetupPanel.tsx. No files changed.')
text=main.read_text(encoding='utf-8')
# Remove only the optional direct/OI PRO worker hook; preserve other lifespan workers.
text=re.sub(r'^\s*install_direct_alerts\(app\)\s*$', '',text,flags=re.M)
if 'app.include_router(trade_setup_router)' not in text:
    block='\nfrom .services.trade_setups import router as trade_setup_router\napp.include_router(trade_setup_router)\n\n'
    pos=text.find('if __name__');text=text[:pos]+block+text[pos:] if pos>=0 else text+block
updates=[(source/'backend/services'/n,root/'backend/services'/n) for n in ('trade_setups.py','option_model.py')]
updates += [(source/'frontend/src'/n,frontend/n) for n in ('TradeSetupPanel.tsx','TradeSetupPanel.css')]
for src,dst in updates:
    if not src.exists():raise SystemExit(f'Missing patch file: {src}')
for src,dst in updates:
    if dst.exists() and not dst.with_name(dst.name+'.before-full-scores').exists():shutil.copy2(dst,dst.with_name(dst.name+'.before-full-scores'))
    shutil.copy2(src,dst)
backup=main.with_name(main.name+'.before-full-scores')
if not backup.exists():shutil.copy2(main,backup)
main.write_text(text,encoding='utf-8')
print('Four score cards restored. Optional direct-alert worker disabled on next restart. Graph and credentials unchanged. Restart backend and frontend.')
