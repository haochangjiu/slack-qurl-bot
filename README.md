# Slack QURL Bot

一个 Slack 机器人，帮助用户通过 LayerV QURL API 生成安全的代理访问链接。

## 功能

- 解析用户消息中的 URL
- 识别用户意图（是否需要代理链接）
- 调用 LayerV API 生成 QURL
- 支持自定义过期时间

## 快速开始

### 1. 创建 Slack App

1. 访问 [Slack API](https://api.slack.com/apps) 创建新应用
2. 选择 "From scratch"，输入应用名称和工作区

### 2. 配置 Bot 权限

在 **OAuth & Permissions** 页面添加以下 Bot Token Scopes:
- `app_mentions:read` - 读取 @提及
- `chat:write` - 发送消息
- `im:history` - 读取私信历史
- `im:read` - 读取私信
- `im:write` - 发送私信

### 3. 启用 Socket Mode

1. 在 **Socket Mode** 页面启用 Socket Mode
2. 生成 App-Level Token (需要 `connections:write` scope)
3. 保存生成的 `xapp-` token

### 4. 订阅事件

在 **Event Subscriptions** 页面:
1. 启用 Events
2. 订阅以下 Bot Events:
   - `app_home_opened`
   - `app_mention`
   - `message.im`

### 5. 安装应用到工作区

在 **Install App** 页面点击安装，获取 `xoxb-` Bot Token

### 6. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件:

```env
# Slack
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# LayerV API (从 LayerV 获取)
LAYERV_API_URL=https://api.layerv.xyz
LAYERV_AUTH0_DOMAIN=your-domain.auth0.com
LAYERV_AUTH0_CLIENT_ID=your-client-id
LAYERV_AUTH0_CLIENT_SECRET=your-client-secret
LAYERV_AUTH0_AUDIENCE=https://api.layerv.ai
```

### 7. 安装依赖并运行

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 运行
python app.py
```

## 使用示例

在 Slack 中:

```
# 私信机器人
google.com 请给我代理地址

# 或在频道中 @提及
@QURLBot https://github.com 帮我生成访问链接 有效期7天

# 英文也支持
@QURLBot example.com proxy please
```

机器人回复:

```
@用户
代理链接已生成:

• 原始网址: google.com
  代理链接: https://xxx.layerv.ai/q/abc123
  有效期至: 2024-01-08T12:00:00Z
```

## 项目结构

```
slack-qurl-bot/
├── app.py              # 主应用 - Slack Bot 逻辑
├── config.py           # 配置管理
├── services/
│   ├── layerv.py       # LayerV QURL API 客户端
│   └── url_parser.py   # URL 提取与解析
├── requirements.txt
├── .env.example
└── README.md
```

## 注意事项

- 需要有效的 LayerV API 凭证
- Bot 使用 Socket Mode，无需公网 IP
- 默认 QURL 有效期为 24 小时，可通过消息指定
