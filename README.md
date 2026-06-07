# Operit Remote Toolkit

通过局域网远程连接 Android 上的 Operit AI 环境，提供聊天、浏览代理、文件管理和进程看守的轻量级工具箱。

专为 **Android proot 环境**及老旧 WebView 设备优化。

---

## 功能特性

- **AI 聊天前端** — 与 Operit API 兼容的对话界面，支持流式 SSE 响应、Markdown 渲染、对话管理
- **浏览代理** — 通过 `/browse/` 端点代理访问外部网页，改写 User-Agent 为桌面版，在老旧设备上也能获得桌面端浏览体验
- **工具箱页面** — 集成多个实用工具的仪表盘：浏览器面板（代理浏览）、文件管理器、端口管理器、代理状态检测
- **Server Keeper** — 进程看守器，自动监测并恢复崩溃的服务端口，带 Web 管理后台和重启趋势图表
- **内嵌分屏浏览** — 点击链接可在分屏中打开目标页面，横屏左右分屏、竖屏上下分屏
- **老旧浏览器适配** — 兼容 Android WebView 102 以下版本，支持低版本内核的 CSS/JS 功能降级

## 项目结构

```
├── toolbox.html              # 工具箱主页面（浏览器面板、文件管理、端口管理）
├── index.html                 # 聊天主界面
├── chat.html                  # 备用聊天页面（单文件，内嵌所有样式和JS）
├── keeper.py                  # Server Keeper 进程看守器
├── server.py                  # HTTP 静态文件服务器 + API 反向代理 + 浏览代理
├── start.sh                   # 一键启动脚本（Android shell）
├── stop.sh                    # 一键停止脚本（Android shell）
├── css/
│   └── style.css              # 主页面样式（浅色/深色模式自适应）
├── js/
│   ├── api.js                 # API 封装（fetch、SSE 解析、时间格式化）
│   ├── chat.js                # 聊天主逻辑（发送消息、流式渲染、对话管理）
│   ├── render.js              # 消息渲染（Markdown、工具调用卡片）
│   └── split.js               # 内嵌浏览器分屏功能
└── test_find.py               # 测试脚本
```

## 端口分配

| 端口 | 角色 | 说明 |
|------|------|------|
| 8094 | API 后端 | Operit AI 聊天核心 API 服务 |
| 8910 | Server Keeper | 看守器 Web 管理后台 + 浏览代理 |
| 8924 | 静态文件服务器 | server.py，提供前端页面 + `/api/*` 反向代理 + `/browse/` 代理 |
| 8925 | 文件服务 | http.server 提供文件下载服务 |
| 8930 | 文件管理器 | http.server 提供文件管理页面 |
| 8931 | 聊天页面 | http.server 运行备用聊天界面 |

## 快速配置

将以下内容发送给你的 Operit AI Agent，即可自动完成依赖安装和服务配置：

```
我需要你在 proot 容器中完成以下操作：

1. 进入工作目录并安装依赖（已安装则跳过）：
   cd /data/user/0/com.ai.assistance.operit/files/workspace/你的工作区ID
   pip install --break-system-packages flask flask-cors requests 2>/dev/null || true

2. 确保 Python 3 可用：
   which python3

3. 启动服务（按顺序）：
   cd /data/user/0/com.ai.assistance.operit/files/workspace/你的工作区ID
   nohup python3 server.py > /sdcard/Download/server_8924.log 2>&1 &
   sleep 2
   nohup python3 keeper.py > /sdcard/Download/keeper_full.log 2>&1 &

4. 确认服务运行：
   for p in 8094 8924 8910 8925 8930 8931; do
     STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$p/ --connect-timeout 2 2>/dev/null)
     echo "端口 $p: $STATUS"
   done

5. 确认浏览代理可用：
   curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8924/browse/https://www.baidu.com --connect-timeout 5

6. 获取本机局域网 IP 并输出：
   ip addr show | grep -E 'inet [0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | awk '{print $2}'
```

## 启动方式

### 方式一：一键启动（Android proot 环境推荐）

```bash
sh start.sh
```

### 方式二：手动启动

```bash
# 1. 确保 API 后端（8094 端口）已在运行

# 2. 启动静态文件服务器（含浏览代理）
python3 server.py

# 3. 启动进程看守器
python3 keeper.py

# 4. 浏览器访问
#    工具箱:  http://<设备IP>:8924/toolbox.html
#    聊天:    http://<设备IP>:8924/index.html
#            http://<设备IP>:8931/index.html
```

## 浏览代理说明

`/browse/` 是内置的网页代理功能，解决老旧 Android WebView 无法正常加载桌面版网页的问题：

1. 代理将 User-Agent 改写为 `Chrome/120 (Windows)`，强制目标网站返回桌面版页面
2. 自动注入 `<base>` 标签，使页面内相对路径资源正确加载
3. 自动注入拦截脚本，使页面内点击链接、提交表单、`window.open` 等操作仍经过代理
4. 支持跨域访问，`Access-Control-Allow-Origin: *`
5. 移除 Content-Security-Policy，避免安全策略阻止资源加载

工具箱页面中的内置浏览器面板默认使用 8910 端口的代理（keeper.py）。

## 技术栈

- **前端**：原生 HTML/CSS/JavaScript（零框架依赖）
- **后端**：Python `http.server` / `socketserver`
- **通信**：REST API + Server-Sent Events（SSE）
- **运行平台**：Linux / Android（proot 容器）

## FAQ

**Q: 提示 403 错误？**
A: 检查 Android proot 环境的网络权限，确保 `/browse/` 代理请求可以通过防火墙。

**Q: 锁屏后其他设备无法访问端口？**
A: Android 省电策略可能限制应用后台网络。在系统设置中将 Operit 的电池策略设为"无限制"，并在 Wi-Fi 高级设置中将"在休眠状态下保持 WLAN 连接"设为"始终"。

**Q: 页面显示为移动版？**
A: 确认使用的是代理端点（`/browse/` 开头），且看守器或 server.py 中 User-Agent 设置有被正确加载。

**Q: proot 容器崩溃重启后外部设备无法访问？**
A: proot 容器重启后可能丢失端口映射。需在 Android 系统层操作，例如通过 `adb forward` 转发端口，或者重启 proot 容器后重新启动服务。

## 许可

MIT
