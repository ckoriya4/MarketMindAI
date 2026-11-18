from pathlib import Path
path=Path('backend/main.py');s=path.read_text(encoding='utf-8')
marker='install_direct_alerts(app)'
if marker not in s:
    backup=path.with_name(path.name+'.before-direct-alerts')
    if not backup.exists():backup.write_text(s,encoding='utf-8')
    block='\nfrom .services.direct_alerts import install_direct_alerts\ninstall_direct_alerts(app)\n\n'
    pos=s.find('if __name__');s=s[:pos]+block+s[pos:] if pos>=0 else s+block
    path.write_text(s,encoding='utf-8')
print('Direct alert router and lifespan worker installed. Restart backend and Vite; one worker only.')
