#!/usr/bin/env python3
"""Server Keeper - 看守器，监控所有端口"""

import subprocess, time, os, json, threading, re, socketserver, collections, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
_BJT = timezone(timedelta(hours=8))
def _ts(fmt):
    return datetime.now(_BJT).strftime(fmt)
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8910; CHECK_INTERVAL = 3
DEVICE_IP = '192.168.1.140'
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(WORK_DIR, 'keeper.log')
MONITOR_FILE = os.path.join(WORK_DIR, 'keeper_ports.txt')
log_buf = []
monitored_ports = {}  # port -> True
_start_time = time.time()
restart_events = []  # [{time, port, duration, result}, ...]
restart_total = {}   # port -> int 每个端口累计重启次数
_restart_cooldown = {}  # port -> last_restart_time 防抖
# 重启历史：按分钟分桶 { 'HH:MM' -> { port: count, ... } }
restart_history = collections.OrderedDict()
_max_history_buckets = 120  # 保留最近 120 分钟（2小时）
HISTORY_FILE = os.path.join(WORK_DIR, 'keeper_history.json')

def _fmt_uptime(secs):
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    if h > 0: return f'{h} 小时 {m} 分钟 {s} 秒'
    if m > 0: return f'{m} 分钟 {s} 秒'
    return f'{s} 秒'

def load_monitored_ports():
    if not os.path.exists(MONITOR_FILE): return
    try:
        with open(MONITOR_FILE) as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    p = int(line)
                    if p != PORT:
                        monitored_ports[p] = True
    except: pass

def save_monitored_ports():
    try:
        ports = sorted(monitored_ports.keys())
        with open(MONITOR_FILE, 'w') as f:
            for p in ports:
                f.write(f'{p}\n')
    except: pass

def add_monitored_port(p):
    if p == PORT: return
    if p not in monitored_ports:
        monitored_ports[p] = True
        save_monitored_ports()

def log(msg):
    ts = _ts('%H:%M:%S')
    line = f'[keeper {ts}] {msg}'
    print(line, flush=True)
    log_buf.append(line)
    if len(log_buf) > 500: log_buf.pop(0)

_log_persist_last = 0
def log_persist(msg):
    global _log_persist_last
    # 防抖：同一秒内只写一次
    now = time.time()
    if now - _log_persist_last < 1:
        return
    _log_persist_last = now
    try:
        ts = _ts('%Y-%m-%d %H:%M:%S')
        with open(LOG_FILE, 'a') as f:
            f.write(f'[{ts}] {msg}\n')
    except:
        pass  # proot 下文件写入可能失败，忽略即可

def load_logs():
    if not os.path.exists(LOG_FILE): return
    try:
        with open(LOG_FILE, 'r') as f:
            for line in f.readlines()[-100:]:
                log_buf.append(line.strip())
    except: pass

# 看守器自己启动的进程 PID 记录（用于可追踪的进程）
_keeper_procs = {}  # port -> proc object
_port_pid_map = {}  # port -> pid string（手动重启时记录）

def find_pid_by_port_scan_proc(port):
    """通过扫描 /proc/*/cmdline 查找监听指定端口的进程 PID"""
    try:
        port_str = str(port)
        for entry in os.listdir('/proc'):
            if not entry.isdigit(): continue
            pid = entry
            try:
                with open(f'/proc/{pid}/cmdline', 'r') as f:
                    cmd = f.read().replace('\0', ' ').strip()
                if not cmd: continue
                # 检查是否是 python http.server 进程，并且包含这个端口
                if port_str in cmd and ('http.server' in cmd or 'python' in cmd):
                    return pid
            except: pass
    except: pass
    return None

def get_process_info(port):
    try:
        pid = find_pid_by_port_scan_proc(port)
        if not pid:
            pid = _port_pid_map.get(port)
        if not pid or pid == '-':
            return {'pid': '-', 'proc': '-', 'started': '-', 'mem': '-'}
        cmdline = '-'; mem = '-'; started = '-'
        try:
            with open(f'/proc/{pid}/cmdline', 'r') as f:
                cmdline = f.read().replace('\0', ' ').strip()[:80]
        except: pass
        try:
            with open(f'/proc/{pid}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        mem = line.split()[1] + ' KB'
                        break
        except: pass
        try:
            import datetime
            with open(f'/proc/{pid}/stat', 'r') as f:
                parts = f.read().split()
            if len(parts) >= 22:
                clk_tck = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
                uptime = float(open('/proc/uptime').read().split()[0])
                start_jiffies = int(parts[21])
                start_seconds = uptime - (start_jiffies / clk_tck)
                boot_time = time.time() - uptime
                start_ts = boot_time + start_seconds
                started = datetime.datetime.fromtimestamp(start_ts).strftime('%H:%M:%S')
        except: pass
        return {'pid': pid, 'proc': cmdline, 'started': started, 'mem': mem}
    except: return None

def get_all_servers():
    srv = []
    for port in range(8000, 10000):
        if port == PORT: continue
        try:
            import http.client
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=0.5)
            c.request('HEAD', '/')
            r = c.getresponse()
            c.close()
            if 200 <= r.status < 400:
                info = get_process_info(port)
                srv.append({
                    'port': str(port),
                    'addr': f'127.0.0.1:{port}',
                    'alive': True,
                    'pid': info['pid'] if info else '?',
                    'proc': info['proc'] if info else '?',
                    'started': info['started'] if info else '?',
                    'mem': info['mem'] if info else '?'
                })
            continue
        except:
            continue
    return srv

def check_port(port):
    try:
        import http.client
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        c.request('HEAD', '/')
        r = c.getresponse()
        c.close()
        return 200 <= r.status < 400
    except: return False

# 看守器自己启动的进程 PID 记录
_keeper_procs = {}  # port -> proc object

def _kill_port_process(port):
    """通过扫描 /proc 找到端口对应进程并 kill，跳过 keeper 自身"""
    port_str = str(port)
    for entry in os.listdir("/proc"):
        if not entry.isdigit(): continue
        try:
            with open(f"/proc/{entry}/cmdline", "r") as f:
                cmd = f.read().replace("\0", " ").strip()
            # 跳过看守器自身
            if "keeper.py" in cmd: continue
            if port_str in cmd and ("http.server" in cmd or "python" in cmd or "server.py" in cmd):
                os.kill(int(entry), 9)
        except: pass
    import time
    time.sleep(0.5)
    return True
def restart_port(port):
    t0 = time.time()
    # 防抖：10 秒内同一个端口不重复重启
    now = time.time()
    last = _restart_cooldown.get(port, 0)
    if now - last < 10:
        return True
    _restart_cooldown[port] = now

    try:
        _kill_port_process(port)
        time.sleep(0.3)
        # 8924 运行 server.py（含浏览代理），其他端口运行 http.server
        if port == 8924:
            cmd_list = ["python3", "server.py"]
            # server.py 绑定端口需要更长时间
            time.sleep(2)
        else:
            cmd_list = ["python3", "-m", "http.server", str(port), "--bind", "0.0.0.0"]
        proc = subprocess.Popen(
            cmd_list,
            cwd=WORK_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=__import__("os").setpgrp)
        dur = round(time.time() - t0, 1)
        _add_restart_event(port, dur, '成功')
        return True
    except:
        dur = round(time.time() - t0, 1)
        _add_restart_event(port, dur, '失败')
        return False

def _save_history():
    """将 restart_history 持久化到 JSON 文件"""
    try:
        # OrderedDict 转成列表 of [key, value] 保持顺序
        data = [[k, v] for k, v in restart_history.items()]
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f)
    except: pass

def _load_history():
    """启动时从 JSON 文件恢复历史数据"""
    try:
        if not os.path.exists(HISTORY_FILE): return
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        for k, v in data:
            restart_history[k] = v
        # 删除过期桶（超过 _max_history_buckets）
        while len(restart_history) > _max_history_buckets:
            restart_history.popitem(last=False)
    except:
        # 文件损坏就清空重来
        restart_history.clear()

def _add_restart_event(port, duration, result):
    ts = _ts('%H:%M:%S')
    restart_events.insert(0, {'time': ts, 'port': port, 'duration': duration, 'result': result})
    if len(restart_events) > 200: restart_events.pop()
    restart_total[port] = restart_total.get(port, 0) + 1
    # 按分钟分桶记录历史
    bucket = _ts('%H:%M')
    if bucket not in restart_history:
        restart_history[bucket] = {}
        if len(restart_history) > _max_history_buckets:
            restart_history.popitem(last=False)  # 移除最旧的桶
    bh = restart_history[bucket]
    bh[port] = bh.get(port, 0) + 1
    # 每次有事件时写入文件
    _save_history()

def check_monitored_port(p):
    """快速检查单个端口是否存活（超时 2 秒）"""
    try:
        import http.client
        c = http.client.HTTPConnection('127.0.0.1', p, timeout=2)
        c.request('HEAD', '/')
        r = c.getresponse()
        c.close()
        return 200 <= r.status < 400
    except:
        return False

def scan_discovery():
    """低频全端口扫描（发现新端口），每 30 秒执行一次"""
    try:
        all_srv = get_all_servers()
        for s in all_srv:
            add_monitored_port(int(s['port']))
    except:
        pass

def monitor_loop():
    scan_timer = 0
    while True:
        try:
            time.sleep(CHECK_INTERVAL)
            # 每隔 30 秒做一次全端口扫描（发现新端口）
            scan_timer += CHECK_INTERVAL
            if scan_timer >= 30:
                scan_timer = 0
                scan_discovery()
            # 快速检查每个已监控端口
            for p in list(monitored_ports.keys()):
                if p == PORT: continue
                if not check_monitored_port(p):
                    msg = f'端口 {p} 已关闭，正在重启...'
                    log(msg); log_persist(msg)
                    ok = restart_port(p)
                    if ok:
                        msg2 = f'端口 {p} 重启成功'
                        log(msg2); log_persist(msg2)
                    else:
                        msg2 = f'端口 {p} 重启失败'
                        log(msg2); log_persist(msg2)
        except Exception as e:
            log(f'监控异常: {e}')

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Server Keeper</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#f8f9fa;padding:16px;color:#1a1a2e}
h1{font-size:20px;margin-bottom:4px;font-weight:700}
.device-ip{font-size:13px;color:#6c757d;margin-bottom:12px}
.card{background:#fff;border:1px solid #e9ecef;border-radius:12px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.card h2{font-size:13px;margin-bottom:10px;color:#495057;text-transform:uppercase;letter-spacing:0.8px;font-weight:600}
.item{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f0f0f0}
.item:last-child{border-bottom:none}
.port-header{display:flex;align-items:center;gap:6px;cursor:pointer;flex:1}
.port-header:hover{opacity:0.6}
.port-label{font-weight:700;font-size:16px;color:#1a1a2e}
.arrow{color:#adb5bd;font-size:12px;transition:transform .2s;user-select:none}
.arrow.open{transform:rotate(90deg)}
.tag{display:inline-block;font-size:10px;padding:2px 6px;border-radius:4px;margin-left:6px;font-weight:500}
.tag-a{background:#e8f5e9;color:#2e7d32;border:none}
.tag-keeper{background:#e3f2fd;color:#1565c0;border:none}
.tag-down{background:#fce4ec;color:#c62828;border:none}
.up{color:#2e7d32;font-weight:600;font-size:13px}
.down{color:#c62828;font-weight:600;font-size:13px}
.detail{display:none;background:#f8f9fa;padding:10px 12px;margin:6px 0 2px;font-size:13px;line-height:1.6;border-radius:8px}
.detail.open{display:block}
.detail-row{display:flex;justify-content:space-between;padding:3px 0}
.detail-label{color:#6c757d}
.detail-value{color:#1a1a2e;word-break:break-all}
.log{background:#1a1a2e;color:#e9ecef;font-family:'SF Mono',monospace;font-size:12px;padding:12px;border-radius:8px;max-height:260px;overflow:auto;white-space:pre-wrap;line-height:1.5}
.btn{display:inline-block;padding:7px 14px;border-radius:8px;border:1px solid #dee2e6;font-size:13px;cursor:pointer;margin-right:6px;margin-top:8px;background:#fff;color:#495057;font-weight:500;transition:all .15s}
.btn:hover{background:#1a1a2e;color:#fff;border-color:#1a1a2e}
.summary{margin-top:8px;font-size:12px;color:#6c757d}
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.stat-box{padding:12px;background:#f8f9fa;border-radius:8px;text-align:center}
.stat-num{font-size:22px;font-weight:700;color:#1a1a2e}
.stat-label{font-size:11px;color:#6c757d;margin-top:2px}
.chart-wrap{position:relative;margin:8px 0}
.chart-wrap canvas{width:100%;height:auto;display:block;border-radius:6px;background:#fafafa}
.chart-title{font-size:12px;color:#6c757d;margin-bottom:4px;font-weight:600}
.rank-bar{display:inline-block;height:6px;border-radius:3px;background:#e8f5e9;margin-right:6px;vertical-align:middle}
.events-list{list-style:none}
.event-item{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12px;border-bottom:1px solid #f0f0f0}
.event-item:last-child{border-bottom:none}
.event-time{color:#adb5bd;font-family:monospace;font-size:11px;min-width:48px}
.event-port{font-weight:600;color:#1a1a2e;min-width:36px}
.event-dur{color:#6c757d}
.event-ok{color:#2e7d32}
.event-fail{color:#c62828}
.event-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.event-dot.ok{background:#2e7d32}
.event-dot.fail{background:#c62828}
</style></head>
<body>
<h1>Server Keeper</h1>
<div class="device-ip">192.168.1.140</div>

<div class="card">
  <h2>所有运行中的服务器</h2>
  <div id="sl">加载中...</div>
  <div class="summary"><span id="count">0</span> 个服务 | 检测间隔: 3s | 看守器: 8932</div>
  <button class="btn" onclick="refresh()">刷新</button>
</div>

<div class="card" id="stats-card">
  <h2>运行统计</h2>
  <div class="stats-grid">
    <div class="stat-box"><div class="stat-num" id="s-uptime">-</div><div class="stat-label">运行时长</div></div>
    <div class="stat-box"><div class="stat-num" id="s-restarts">-</div><div class="stat-label">重启次数</div></div>
    <div class="stat-box"><div class="stat-num" id="s-monitored">-</div><div class="stat-label">监控端口</div></div>
    <div class="stat-box"><div class="stat-num" id="s-active">-</div><div class="stat-label">在线服务</div></div>
  </div>
  <div id="stats-detail"></div>
</div>

<div class="card">
  <h2>日志</h2>
  <div class="log" id="log">加载中...</div>
  <button class="btn" onclick="document.getElementById('log').textContent='(已清空)';fetch('/api/clear-logs',{method:'POST'})">清空日志</button>
</div>

<script>
var openPort='';
function toggleDetail(port){
  var el=document.getElementById('d-'+port);
  var ar=document.getElementById('a-'+port);
  if(!el)return;
  if(openPort==port){openPort='';el.classList.remove('open');if(ar)ar.classList.remove('open');return}
  if(openPort){
    var oldEl=document.getElementById('d-'+openPort);
    var oldAr=document.getElementById('a-'+openPort);
    if(oldEl)oldEl.classList.remove('open');
    if(oldAr)oldAr.classList.remove('open');
  }
  openPort=port;
  el.classList.add('open');
  if(ar)ar.classList.add('open');
}

var _chartColors = ['#4caf50','#2196f3','#ff9800','#e91e63','#9c27b0','#00bcd4','#ff5722','#795548','#607d8b','#3f51b5'];
function drawLineChart(canvasId, history, ports){
  var canvas = document.getElementById(canvasId);
  if(!canvas) return;
  var ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
  var pad = {t:18,b:20,l:32,r:10}, cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
  ctx.clearRect(0,0,W,H);
  if(!history || history.length < 2) return;
  // 获取所有端口在每个时间点的总次数（求和）
  var arr = [];
  for(var i=0;i<history.length;i++){
    var h = history[i], sum=0;
    for(var k in h.ports) sum += h.ports[k];
    arr.push(sum);
  }
  var maxV = Math.max.apply(null, arr);
  if(maxV === 0) return;
  var stepX = cw / (arr.length - 1);
  // 画网格线和Y轴标签
  ctx.strokeStyle='#e0e0e0'; ctx.lineWidth=0.5;
  for(var y=0;y<=4;y++){
    var yy = pad.t + ch - (y/4)*ch;
    ctx.beginPath(); ctx.moveTo(pad.l,yy); ctx.lineTo(W-pad.r,yy); ctx.stroke();
    ctx.fillStyle='#999'; ctx.font='9px sans-serif'; ctx.textAlign='right';
    ctx.fillText(Math.round(maxV*y/4), pad.l-4, yy+3);
  }
  // 画折线
  ctx.strokeStyle='#4caf50'; ctx.lineWidth=1.5; ctx.beginPath();
  for(var i=0;i<arr.length;i++){
    var x = pad.l + i*stepX, y = pad.t + ch - (arr[i]/maxV)*ch;
    if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }
  ctx.stroke();
  // 画数据点
  for(var i=0;i<arr.length;i++){
    var x = pad.l + i*stepX, y = pad.t + ch - (arr[i]/maxV)*ch;
    ctx.fillStyle='#4caf50'; ctx.beginPath(); ctx.arc(x,y,2,0,Math.PI*2); ctx.fill();
  }
  // X轴标签（只显示首尾和中间几个）
  var labelStep = Math.max(1, Math.floor(arr.length/6));
  ctx.fillStyle='#999'; ctx.font='8px sans-serif'; ctx.textAlign='center';
  for(var i=0;i<arr.length;i+=labelStep){
    var x = pad.l + i*stepX;
    ctx.fillText(history[i].time, x, H-4);
  }
}

function drawBarChart(canvasId, topPorts){
  var canvas = document.getElementById(canvasId);
  if(!canvas || !topPorts || !topPorts.length) return;
  var ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
  var pad = {t:14,b:18,l:50,r:10}, cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
  ctx.clearRect(0,0,W,H);
  var n = topPorts.length, maxC = topPorts[0].count;
  if(maxC === 0) return;
  var barH = Math.min(18, ch/n - 4);
  var totalH = n*(barH+4);
  var startY = pad.t + (ch - totalH)/2;
  for(var i=0;i<n;i++){
    var r = topPorts[i], pct = r.count/maxC, w = cw * pct;
    var y = startY + i*(barH+4);
    // 柱
    var ci = i % _chartColors.length;
    ctx.fillStyle = _chartColors[ci]; ctx.fillRect(pad.l, y, w, barH);
    // 端口名
    ctx.fillStyle='#333'; ctx.font='10px sans-serif'; ctx.textAlign='right';
    ctx.fillText(r.port, pad.l-4, y+barH-2);
    // 次数
    ctx.fillStyle='#666'; ctx.font='9px sans-serif'; ctx.textAlign='left';
    ctx.fillText(r.count+'次', pad.l+w+4, y+barH-2);
  }
}

function renderStats(d){
  document.getElementById('s-uptime').textContent = d.uptime_human;
  document.getElementById('s-restarts').textContent = d.total_restarts;
  document.getElementById('s-monitored').textContent = d.monitored_count;
  var html='';
  // 折线图
  if(d.history && d.history.length >= 2){
    html += '<div class="chart-wrap"><div class="chart-title">重启频次趋势</div><canvas id="line-chart" width="320" height="130"></canvas></div>';
  }
  // 柱状图
  if(d.top_ports && d.top_ports.length){
    html += '<div class="chart-wrap"><div class="chart-title">各端口重启次数</div><canvas id="bar-chart" width="320" height="'+Math.min(180, 30+d.top_ports.length*22)+'"></canvas></div>';
  }
  // 最近事件
  if(d.recent_events && d.recent_events.length){
    html += '<div style="margin-top:8px;font-size:12px;color:#6c757d;margin-bottom:4px">最近事件</div>';
    html += '<div class="events-list">';
    d.recent_events.slice(0,8).forEach(function(e){
      var cls = e.result=='成功'?'ok':'fail';
      html += '<div class="event-item"><span class="event-dot '+cls+'"></span><span class="event-time">'+e.time+'</span><span class="event-port">'+e.port+'</span><span class="event-dur">'+e.duration+'s</span><span class="event-'+cls+'">'+e.result+'</span></div>';
    });
    html += '</div>';
  }
  document.getElementById('stats-detail').innerHTML = html;
  // 绘制图表（延迟一下确保 DOM 已更新）
  setTimeout(function(){
    drawLineChart('line-chart', d.history, d.top_ports);
    drawBarChart('bar-chart', d.top_ports);
  }, 50);
}

function refresh(){
  fetch('/api/servers').then(function(r){return r.json()}).then(function(d){
    var sl=document.getElementById('sl'), ip=d.device_ip||'192.168.1.140';
    document.getElementById('count').textContent=d.servers.length;
    document.getElementById('s-active').textContent=d.servers.length;
    if(d.servers.length===0){sl.innerHTML='<div style="color:#6c757d;padding:8px 0">无运行中的服务器</div>';return}
    sl.innerHTML=d.servers.map(function(s){
      var alive=s.alive;
      var tag = s.port==d.self_port ? '<span class="tag tag-keeper">看守器</span>' :
                (alive?'<span class="tag tag-a">活跃</span>':'<span class="tag tag-down">已关闭</span>');
      var statusClass=alive?'up':'down';
      var statusText=alive?'运行中':'已关闭';
      var openClass=(openPort==s.port)?' open':'';
      return '<div class="item">'+
        '<div class="port-header" onclick="toggleDetail('+s.port+')">'+
          '<span class="arrow'+(openPort==s.port?' open':'')+'" id="a-'+s.port+'">></span>'+
          '<span class="port-label">'+s.port+'</span>'+
          tag+
        '</div>'+
        '<span class="'+statusClass+'">'+statusText+'</span>'+
      '</div>'+
      '<div class="detail'+openClass+'" id="d-'+s.port+'">'+
        '<div class="detail-row"><span class="detail-label">PID</span><span class="detail-value">'+s.pid+'</span></div>'+
        '<div class="detail-row"><span class="detail-label">进程</span><span class="detail-value">'+s.proc+'</span></div>'+
        '<div class="detail-row"><span class="detail-label">内存</span><span class="detail-value">'+s.mem+'</span></div>'+
        '<div class="detail-row"><span class="detail-label">启动时间</span><span class="detail-value">'+s.started+'</span></div>'+
        '<div class="detail-row"><span class="detail-label">地址</span><span class="detail-value"><a href="http://'+ip+':'+s.port+'" target="_blank">http://'+ip+':'+s.port+'</a></span></div>'+
      '</div>';
    }).join('');
  });
  fetch('/api/logs').then(function(r){return r.json()}).then(function(d){
    var el=document.getElementById('log');
    el.textContent=d.logs.join('\\n')||'(无日志)';
    el.scrollTop=el.scrollHeight;
  });
  fetch('/api/stats').then(function(r){return r.json()}).then(renderStats);
}
refresh();setInterval(refresh,5000);
</script>
</body></html>"""

import socket
class ReuseServer(HTTPServer):
    allow_reuse_address = True
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        socketserver.TCPServer.server_bind(self)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/servers':
            s = get_all_servers()
            self.send_json({'servers': s, 'self_port': PORT, 'device_ip': DEVICE_IP, 'check_interval': CHECK_INTERVAL})
        elif self.path == '/api/logs':
            self.send_json({'logs': list(log_buf)})
        elif self.path == '/api/stats':
            uptime = round(time.time() - _start_time)
            top_ports = sorted(restart_total.items(), key=lambda x: -x[1])[:10]
            # 构建历史时间线：按时间顺序排列的分钟桶
            history_timeline = []
            for bk, v in restart_history.items():
                history_timeline.append({'time': bk, 'ports': dict(v)})
            self.send_json({
                'uptime': uptime,
                'uptime_human': _fmt_uptime(uptime),
                'total_restarts': sum(restart_total.values()),
                'monitored_count': len(monitored_ports),
                'top_ports': [{'port': p, 'count': c} for p, c in top_ports],
                'recent_events': list(restart_events[:20]),
                'history': history_timeline
            })
        elif self.path.startswith('/browse/'):
            # 解析目标 URL：支持 /browse/?url=xxx 和 /browse/xxx 两种格式
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            target_url = params.get('url', [None])[0]
            if not target_url:
                target_url = urllib.parse.unquote(self.path[len('/browse/'):])
            if not target_url:
                self.send_error(400, 'Missing url parameter')
                return
            try:
                import ssl
                req = urllib.request.Request(
                    target_url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    }
                )
                ctx = ssl._create_unverified_context()
                resp = urllib.request.urlopen(req, timeout=15, context=ctx)
                content = resp.read()
                content_type = resp.headers.get('Content-Type', 'text/html')
                if 'text/html' in content_type:
                    charset = 'utf-8'
                    ct_lower = content_type.lower()
                    if 'charset=' in ct_lower:
                        charset = ct_lower.split('charset=')[-1].split(';')[0].strip()
                    html = content.decode(charset, errors='replace')
                    # 注入 <base> 标签，让相对路径资源正确加载
                    base_tag = '<base href="' + target_url.rstrip('/') + '/">'
                    if '<head>' in html:
                        html = html.replace('<head>', '<head>' + base_tag, 1)
                    else:
                        html = base_tag + html
                    # 移除 Content-Security-Policy meta 标签
                    html = re.sub(r'<meta[^>]+http-equiv=["\']Content-Security-Policy["\'][^>]*>', '', html, flags=re.IGNORECASE)
                    # 注入JS：拦截所有链接点击, 表单提交, window.open, 以及捕获新打开的页面请求,全部走回代理
                    proxy_base = 'http://' + DEVICE_IP + ':' + str(PORT) + '/browse/'
                    hijack_js = '''
<script>
(function(){
  var PROXY = ''' + json.dumps(proxy_base) + ''';
  var _currentUrl = window.location.href;
  function notifyParent(url){
    if(url && url !== _currentUrl){
      _currentUrl = url;
      parent.postMessage({type:'url-change',url:url}, '*');
    }
  }
  // 拦截链接点击
  document.addEventListener('click', function(e){
    var a = e.target.closest('a');
    if(!a || !a.href) return;
    var href = a.getAttribute('href');
    if(!href || href.startsWith('#') || href.startsWith('javascript:')) return;
    if(a.href.startsWith(PROXY)) return;
    e.preventDefault();
    window.location.href = PROXY + encodeURIComponent(a.href);
  }, true);
  // 拦截表单提交
  document.addEventListener('submit', function(e){
    var form = e.target;
    if(!form || !form.action) return;
    if(form.action.startsWith(PROXY)) return;
    e.preventDefault();
    var data = new URLSearchParams(new FormData(form));
    var url = form.action + (form.action.includes('?')?'&':'?') + data.toString();
    window.location.href = PROXY + encodeURIComponent(url);
  }, true);
  // 拦截 window.open
  var origOpen = window.open;
  window.open = function(url, name, features){
    if(url && !url.startsWith(PROXY)){
      url = PROXY + encodeURIComponent(url);
    }
    return origOpen.call(window, url, name, features);
  };
  // 劫持 history.pushState / replaceState
  var _origPushState = history.pushState;
  var _origReplaceState = history.replaceState;
  history.pushState = function(state, title, url){
    _origPushState.call(this, state, title, url);
    notifyParent(window.location.href);
  };
  history.replaceState = function(state, title, url){
    _origReplaceState.call(this, state, title, url);
    notifyParent(window.location.href);
  };
  window.addEventListener('popstate', function(){
    notifyParent(window.location.href);
  });
  // 劫持 location.href 赋值
  var _loc = window.location;
  Object.defineProperty(_loc, 'href', {
    set: function(val){
      if(!val.startsWith(PROXY) && !val.startsWith('#') && !val.startsWith('javascript:')){
        val = PROXY + encodeURIComponent(val);
      }
      notifyParent(val);
      _loc.assign(val);
    },
    get: function(){ return _loc.href; }
  });
  // 劫持 location.assign / location.replace
  var _origAssign = _loc.assign;
  var _origReplace = _loc.replace;
  _loc.assign = function(url){
    if(url && !url.startsWith(PROXY) && !url.startsWith('#') && !url.startsWith('javascript:')){
      url = PROXY + encodeURIComponent(url);
    }
    notifyParent(url);
    _origAssign.call(_loc, url);
  };
  _loc.replace = function(url){
    if(url && !url.startsWith(PROXY) && !url.startsWith('#') && !url.startsWith('javascript:')){
      url = PROXY + encodeURIComponent(url);
    }
    notifyParent(url);
    _origReplace.call(_loc, url);
  };
  // 页面完全加载后通知父页面当前 URL
  window.addEventListener('load', function(){ notifyParent(window.location.href); });
  if(document.readyState === 'complete'){ notifyParent(window.location.href); }
  else { document.addEventListener('DOMContentLoaded', function(){ notifyParent(window.location.href); }); }
})();
</script>
'''
                    body_close_idx = html.rfind('</body>')
                    if body_close_idx > 0:
                        html = html[:body_close_idx] + hijack_js + html[body_close_idx:]
                    else:
                        html += hijack_js
                    content = html.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('X-Frame-Options', 'ALLOWALL')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.send_response(resp.status)
                    for h in ['Content-Type', 'Content-Length', 'Cache-Control']:
                        if h in resp.headers:
                            self.send_header(h, resp.headers[h])
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(content)
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                err_page = '<html><body style="padding:20px;font-family:sans-serif"><h3>代理错误</h3><p>' + str(e) + '</p></body></html>'
                self.wfile.write(err_page.encode('utf-8'))
        else:
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin','*')
            self.end_headers()
            self.wfile.write(HTML.encode('utf-8'))
    def do_POST(self):
        if self.path.startswith('/api/restart/'):
            port = self.path.split('/')[-1]
            if port.isdigit():
                ok = restart_port(int(port))
                self.send_json({'success': ok, 'message': f'端口 {port} 重启{"成功" if ok else "失败"}'})
                if ok: log_persist(f'手动重启端口 {port} 成功')
        elif self.path == '/api/clear-logs':
            log_buf.clear()
            self.send_json({'success': True})
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin','*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    def log_message(self,*a): pass

if __name__ == '__main__':
    load_logs()
    _load_history()
    load_monitored_ports()
    cnt = len(monitored_ports)
    hcnt = len(restart_history)
    log(f'看守器启动 自身端口={PORT} 已加载 {cnt} 个监控端口, 历史数据 {hcnt} 分钟')
    log_persist(f'看守器启动 自身端口={PORT} 加载 {cnt} 个监控端口')
    # 自动恢复所有已记录的端口
    for p in list(monitored_ports.keys()):
        if p == PORT: continue
        try:
            import http.client
            c = http.client.HTTPConnection('127.0.0.1', p, timeout=1)
            c.request('HEAD', '/')
            r = c.getresponse()
            c.close()
            if 200 <= r.status < 400:
                continue
        except:
            log(f'自动恢复端口 {p}')
            restart_port(p)
    t = threading.Thread(target=monitor_loop, daemon=True)
    t.start()
    for retry in range(30):
        try:
            server = ReuseServer(('0.0.0.0', PORT), Handler)
            break
        except OSError as e:
            if 'Address already in use' in str(e) and retry < 29:
                time.sleep(2)
                continue
            raise
    log(f'管理后台: http://0.0.0.0:{PORT}')
    try: server.serve_forever()
    except Exception as e: log(f'看守器异常终止: {e}'); log_persist(f'看守器异常终止: {e}')
    except: log('看守器异常终止(未知)'); log_persist('看守器异常终止(未知)')
