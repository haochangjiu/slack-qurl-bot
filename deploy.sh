#!/bin/bash
set -e

# Slack QURL Bot 部署脚本
# 使用方法: bash deploy.sh

APP_DIR="/opt/slack-qurl-bot"
SERVICE_NAME="slack-qurl-bot"

echo "=== Slack QURL Bot 部署脚本 ==="

# 检查是否为 root
if [ "$EUID" -ne 0 ]; then
    echo "请使用 sudo 运行此脚本"
    exit 1
fi

# 1. 安装系统依赖
echo "[1/6] 安装系统依赖..."
apt update -qq
apt install -y python3 python3-venv python3-pip

# 2. 创建目录
echo "[2/6] 创建应用目录..."
mkdir -p $APP_DIR
cp -r . $APP_DIR/ 2>/dev/null || true
cd $APP_DIR

# 3. 创建虚拟环境
echo "[3/6] 创建 Python 虚拟环境..."
python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# 4. 检查 .env 文件
echo "[4/6] 检查配置文件..."
if [ ! -f "$APP_DIR/.env" ]; then
    echo "警告: .env 文件不存在，请创建并配置:"
    echo "  cp $APP_DIR/.env.example $APP_DIR/.env"
    echo "  nano $APP_DIR/.env"
fi

# 5. 创建 systemd 服务
echo "[5/6] 创建 systemd 服务..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=Slack QURL Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 6. 启动服务
echo "[6/6] 启动服务..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME
systemctl restart $SERVICE_NAME

echo ""
echo "=== 部署完成 ==="
echo ""
echo "常用命令:"
echo "  查看状态: systemctl status $SERVICE_NAME"
echo "  查看日志: journalctl -u $SERVICE_NAME -f"
echo "  重启服务: systemctl restart $SERVICE_NAME"
echo "  停止服务: systemctl stop $SERVICE_NAME"
echo ""

# 显示服务状态
systemctl status $SERVICE_NAME --no-pager
