import os
port = 8931
for entry in os.listdir('/proc'):
    if not entry.isdigit(): continue
    pid = entry
    try:
        with open(f'/proc/{pid}/cmdline', 'r') as f:
            cmd = f.read().replace('\0', ' ').strip()
        if f'http.server {port}' in cmd:
            print(f'Found: pid={pid} cmd={cmd}')
    except:
        pass
print('Done')
