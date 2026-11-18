from pathlib import Path
import re,shutil
root=Path.cwd();source=Path(__file__).resolve().parent
main=root/'backend/main.py';front=root/'frontend/src'
if not front.exists():front=root/'src'
app=front/'App.tsx'
if not main.exists() or not app.exists():raise SystemExit('Run from existing dashboard project root. No files changed.')
pairs=[(source/'backend/services/kite_login.py',root/'backend/services/kite_login.py'),(source/'frontend/src/KiteLoginButton.tsx',front/'KiteLoginButton.tsx')]
for src,dst in pairs:
 if not src.exists():raise SystemExit(f'Missing package file: {src}. Extract the complete ZIP. No files changed.')
s=main.read_text(encoding='utf-8');a=app.read_text(encoding='utf-8')
if '<KiteLoginButton' not in a:
 match=re.search(r'<b><Activity[^\n]+BACKEND ONLINE[^\n]+</b>',a)
 if not match:raise SystemExit('Status strip not recognized. No files changed.')
 a=a[:match.end()]+'\n      <KiteLoginButton />'+a[match.end():]
 a='import KiteLoginButton from "./KiteLoginButton";\n'+a
if 'app.include_router(kite_login_router)' not in s:
 block='\nfrom .services.kite_login import router as kite_login_router\napp.include_router(kite_login_router)\n\n'
 pos=s.find('if __name__');s=s[:pos]+block+s[pos:] if pos>=0 else s+block
compile(s,str(main),'exec')
for p,text in [(main,s),(app,a)]:
 backup=p.with_name(p.name+'.before-kite-login')
 if not backup.exists():shutil.copy2(p,backup)
 p.write_text(text,encoding='utf-8')
for src,dst in pairs:
 if src.resolve()!=dst.resolve():
  if dst.exists() and src.samefile(dst):continue
  shutil.copy2(src,dst)
# Never copy real credentials or tokens into version control.
gitignore=root/'.gitignore';existing=gitignore.read_text() if gitignore.exists() else ''
lines=['backend/.env','backend/.env.*','!backend/.env.example']
for line in lines:
 if line not in existing.splitlines():existing+='\n'+line
 gitignore.write_text(existing,encoding='utf-8')
print('Kite browser login installed. Set key/secret once and developer-console redirect URL to http://127.0.0.1:8000/api/auth/kite/callback . Restart backend/frontend. Use http://127.0.0.1:5173 .')
