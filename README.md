# Hermes QQ Bot 迁移包 (Hermes-QQBot Migration Package)

本仓库是一个专门为 **Hermes** 生态设计的迁移包，旨在帮助用户将 **QQ Bot** 的支持快速迁入原本不支持该平台的 Hermes 代码库中。

> **注意：** 本仓库仅包含实现逻辑、代码快照和配置模板，**不包含任何真实密钥或凭据**。

---

## 🚀 项目目的
原本的 Hermes 代码库可能仅支持 Telegram、Discord 等平台。本迁移包提供了经过验证的 **QQ Bot WebSocket Gateway** 接入实现，帮助您补齐以下能力：
- 基于 WebSocket 的消息收发（支持私聊、群组 @）
- 平台适配器、工具集（Toolset）注册
- 消息投递（Cron Delivery）支持
- 自动设置 Home Channel

---

## 📂 目录结构说明

- **`source_snapshot/`**: 核心源码快照。包含从成功运行的环境中提取的适配器、配置修改、工具注册等文件。
- **`templates/`**: 配置模板。
    - `config.qqbot.template.yaml`: 用于合并到 `~/.hermes/config.yaml`。
    - `qqbot.env.template`: 环境变量配置示例。
- **`docs/`**: 文档与清单。
    - `manifest.json`: 包含的文件列表。
- **`README_迁移指南.md`**: **必读！** 详细记录了迁移步骤、代码比对建议及常见问题处理。

---

## 🛠 快速开始

### 1. 前置依赖
确保您的环境已安装以下 Python 库：
```bash
pip install websockets httpx
```

### 2. 代码比对与迁入
参考 `source_snapshot/` 目录，将相关代码块（特别是 `gateway/platforms/qqbot.py`）合并到您的目标仓库。**建议使用人工 Diff 合并**，以免覆盖掉目标仓库中已有的其他平台逻辑。

### 3. 配置凭据
参考 `templates/` 中的模板，将您的 `AppID`、`Secret` 和 `Token` 填入配置：
- 推荐方式：修改 `~/.hermes/config.yaml`。
- 备选方式：设置环境变量 `QQBOT_APP_ID`、`QQBOT_SECRET` 等。

### 4. 重启与验证
重启您的 `hermes-gateway` 进程，并在 QQ 中对机器人发送消息。如果收到响应，说明基础链路已通。
执行 `/sethome` 命令以初始化 Home Channel。

---

## ⚠️ 安全警告
- **严禁**将包含真实 `AppID` 或 `Token` 的配置文件提交到任何公开仓库。
- 本代码包基于特定的成功案例快照，若目标代码库结构已发生重大重构，请将其作为参考实现而非直接覆盖。

---

## 🤝 贡献与反馈
如果您在迁移过程中发现兼容性问题或有更好的实现方案，欢迎提交 Issue 或 Pull Request。
