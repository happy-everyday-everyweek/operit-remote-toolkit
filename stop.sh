#!/system/bin/sh
# 一键停止所有服务
# 用法: sh stop.sh

WORK_DIR="/data/user/0/com.ai.assistance.operit/files/workspace/dc071d7c-eebc-4f86-a5af-b7140bb7afb5"
echo "[stop] 正在停止所有服务..."

# 依次停止 server.py、keeper.py 和所有 http.server 进程
pkill -f "${WORK_DIR}/server.py" 2>/dev/null
pkill -f "${WORK_DIR}/keeper.py" 2>/dev/null
pkill -f "http.server" 2>/dev/null

sleep 1

# 检查是否还有残留进程
REMAIN=$(ps -ef | grep -E "server\.py|keeper\.py|http\.server" | grep -v grep)
if [ -z "$REMAIN" ]; then
    echo "[stop] 所有服务已停止"
else
    echo "[stop] 警告：仍有残留进程"
    echo "$REMAIN"
fi
