from pathlib import Path
path=Path('backend/main.py');s=path.read_text(encoding='utf-8')
marker='app.include_router(oi_reference_router)'
if marker not in s:
    backup=path.with_name(path.name+'.before-percent-reference')
    if not backup.exists():backup.write_text(s,encoding='utf-8')
    block='\nfrom .services.oi_percent_reference import router as oi_reference_router\napp.include_router(oi_reference_router)\n\n'
    pos=s.find('if __name__');s=s[:pos]+block+s[pos:] if pos>=0 else s+block
    path.write_text(s,encoding='utf-8')
print('OI percentage-reference route installed. Restart backend and Vite.')
