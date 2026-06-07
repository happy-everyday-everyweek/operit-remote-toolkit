#!/system/bin/sh
# 一键启动所有服务（含浏览代理）
# 用法: sh start.sh

WORK_DIR="/data/user/0/com.ai.assistance.operit/files/workspace/dc071d7c-eebc-4f86-a5af-b7140bb7afb5"
cd "$WORK_DIR" || exit 1

echo "[start] 清理残留进程..."
pkill -f "python3 server.py" 2>/dev/null
pkill -f "python3 keeper.py" 2>/dev/null
pkill -f "python3 -m http.server" 2>/dev/null
sleep 1

echo "[start] 启动 server.py（8924端口，含浏览代理）..."
nohup python3 server.py > /sdcard/Download/server_8924.log 2>&1 &
echo "[start] server.py PID=$!"

sleep 2

echo "[start] 启动看守器（8910端口，自动拉起其他端口）..."
nohup python3 keeper.py > /sdcard/Download/keeper_full.log 2>&1 &
echo "[start] keeper.py PID=$!"

echo "[start] 等待服务启动..."
sleep 8

echo ""
echo "[start] 端口状态检查："
for p in 8094 8924 8925 8930 8931 8910; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:$p/ --connect-timeout 2 2>/dev/null)
  echo "  端口 $p: $STATUS"
done
echo ""
echo "[start] 浏览代理测试："
BROWSE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8924/browse/https://www.baidu.com --connect-timeout 5 2>/dev/null)
echo "  8924/browse/: $BROWSE_STATUS"
echo ""
echo "[start] 服务启动完成"
echo "  工具箱（含浏览代理）: http://192.168.1.140:8924/toolbox.html"
echo "  聊天页面:              http://192.168.1.140:8931/index.html"
