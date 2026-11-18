"""Run from project root after copying package files; preserve existing dashboard edits."""
from pathlib import Path
import re
main=Path('backend/main.py');app=Path('frontend/src/App.tsx')
if not app.exists():app=Path('src/App.tsx')
s=main.read_text(encoding='utf-8');a=app.read_text(encoding='utf-8')
if '<TradeSetupPanel' not in a:
    match=re.search(r'<section\s+className=["\']panel options["\']\s*>',a)
    if not match:raise SystemExit('Option-chain section not found. Add TradeSetupPanel above it manually; no files changed.')
    depth=0;end=None
    for tag in re.finditer(r'</?section\b[^>]*>',a[match.start():]):
        depth+=-1 if tag.group().startswith('</') else 1
        if depth==0:end=match.start()+tag.end();break
    if end is None:raise SystemExit('Cannot locate option-chain closing section; no files changed.')
    props=' expiry={selectedExpiry || chainData?.selected_expiry || ""}' if 'selectedExpiry' in a and 'chainData' in a else ''
    a=a[:match.start()]+'<div className="option-action-stack">\n      <TradeSetupPanel'+props+' />\n      '+a[match.start():end]+'\n      </div>'+a[end:]
    a='import TradeSetupPanel from "./TradeSetupPanel";\n'+a
if 'app.include_router(trade_setup_router)' not in s:
    addition='\nfrom .services.trade_setups import router as trade_setup_router\napp.include_router(trade_setup_router)\n\n'
    pos=s.find('if __name__');s=s[:pos]+addition+s[pos:] if pos>=0 else s+addition
for path,text in [(main,s),(app,a)]:
    backup=path.with_name(path.name+'.before-trade-panel')
    if not backup.exists():backup.write_text(path.read_text(encoding='utf-8'),encoding='utf-8')
    path.write_text(text,encoding='utf-8')
print('Four setup cards installed above option chain. Restart backend and Vite.')
