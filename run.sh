#!/usr/bin/env bash
# ============================================================
# 教学bot 一键部署（Ubuntu 服务器机 · 无需 root）
# 用法：把整个部署包拷到服务器上，然后：
#   cd 教学bot_学校部署包 && bash run.sh
# 效果：启动服务 + 注册开机自启 + 每5分钟看门狗
# ============================================================
cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null; then
  echo "✘ 缺少 python3，请先执行：sudo apt install -y python3"
  exit 1
fi

mkdir -p data

# AI key 自检：config.json 里 key 为空时，尝试用同目录 key.txt 补上
python3 - <<'PYEOF'
import json
try:
    cfg = json.load(open('config.json', encoding='utf-8'))
except Exception:
    cfg = {}
if not cfg.get('api_key'):
    try:
        k = open('key.txt', encoding='utf-8').read().strip()
        if k:
            cfg['api_key'] = k
            json.dump(cfg, open('config.json', 'w', encoding='utf-8'), indent=1)
            print('✔ 已从 key.txt 补上 AI key')
    except Exception:
        pass
    if not cfg.get('api_key'):
        print('△ 未设 AI key：12学科网站/练习系统/收卷学情 都可用；AI出题/AI助教 不可用。')
        print('  启用方法：在本目录建一个 key.txt，内容一行粘贴 sk-... 的 key，再重跑 bash run.sh')
PYEOF

if pgrep -f "teachbot.py" >/dev/null 2>&1; then
  echo "✔ 服务已在运行"
else
  nohup python3 teachbot.py >> server.log 2>&1 &
  sleep 2
  if pgrep -f "teachbot.py" >/dev/null 2>&1; then
    echo "✔ 服务已启动"
  else
    echo "✘ 启动失败，看日志：cat server.log"
    exit 1
  fi
fi

# 探测局域网 IP
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -z "$IP" ] && IP=$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0])" 2>/dev/null)

# 注册开机自启 + 每5分钟看门狗（user crontab，不需要 root）
SELF="$(cd "$(dirname "$0")"; pwd)"
( crontab -l 2>/dev/null | grep -v "teachbot" ; \
  echo "@reboot cd $SELF && bash run.sh >/dev/null 2>&1"; \
  echo "*/5 * * * * pgrep -f 'teachbot.py' >/dev/null || cd $SELF && bash run.sh >/dev/null 2>&1" ) | crontab -

echo "======================================================"
echo " 学生/老师打开:  http://$IP:8377/"
echo " 学生作答页:     http://$IP:8377/quiz/"
echo " 教师面板:       http://$IP:8377/report/"
echo " AI 助教:        http://$IP:8377/tutor/"
echo " 已注册开机自启 + 看门狗（每5分钟自动拉起）"
echo " 查日志:         tail -f $SELF/server.log"
echo "======================================================"
