# 另一套 Hermes 代码库原本没有 QQ Bot 支持时的迁移指南

目标：
让“原本没有 qqbot 支持代码”的另一套 Hermes，基于本目录中的代码快照、模板配置和迁移步骤，顺利跑通 QQ Bot。

重要说明：
1. 本目录不是单纯经验文档，而是“文档 + 代码快照 + 配置模板”的迁移包。
2. source_snapshot 中放的是当前已验证成功环境里的相关源码文件快照。
3. 目标代码库如果完全没有 qqbot 支持，不要只照着配 config，必须把相关源码改动一起迁入。
4. 本迁移包不包含任何真实 QQ Bot 密钥。

-----------------------------------
一、目录说明
-----------------------------------

1. source_snapshot/
   当前成功环境中，与 qqbot 接入相关的源码文件快照。

2. templates/config.qqbot.template.yaml
   写入 ~/.hermes/config.yaml 的模板片段。

3. templates/qqbot.env.template
   可选的环境变量模板。

4. docs/manifest.json
   本迁移包包含文件清单。

-----------------------------------
二、迁移目标的前提假设
-----------------------------------

适用场景：
- 目标 Hermes 代码库目前没有 qqbot 支持
- 目标代码库可能缺少 qqbot 平台适配器
- 目标代码库可能缺少平台注册、工具集、gateway 入口、发送逻辑、状态展示等兼容代码

不适用场景：
- 目标代码库结构与当前 Hermes 完全不同，关键模块名已大改
- 目标代码库不是 Hermes 或已重构成不兼容架构

如果目标代码库与当前结构差异过大，应把本迁移包当参考实现，而不是无脑覆盖。

-----------------------------------
三、QQ Bot 接入成功所需的最小代码集合
-----------------------------------

本次成功经验表明，至少要具备以下能力：

A. 平台枚举与配置层
- gateway/config.py
- hermes_cli/tools_config.py
- hermes_cli/gateway.py
- hermes_cli/status.py

B. 平台运行时接入层
- gateway/platforms/qqbot.py
- gateway/run.py
- gateway/channel_directory.py

C. 工具集与消息投递层
- toolsets.py
- tools/send_message_tool.py
- cron/scheduler.py

D. 平台提示词/展示层
- agent/prompt_builder.py

结论：
如果目标代码库完全没有 qqbot 支持，至少要把上述代码能力迁进去，单改 config.yaml 是不够的。

-----------------------------------
四、建议迁移顺序
-----------------------------------

第 1 步：先备份目标代码库

在目标 Hermes 仓库执行：
1. 建立新分支
2. 备份以下可能被修改的文件
3. 不要直接在主分支覆盖

建议：
- git checkout -b feature/qqbot-support


第 2 步：比对代码结构是否兼容

把目标仓库与本迁移包中的 source_snapshot/ 对照，重点看这些路径是否存在：
- gateway/
- gateway/platforms/
- hermes_cli/
- tools/
- agent/
- cron/
- toolsets.py

如果这些路径基本一致，可以采用“人工 diff + 逐文件迁移”。


第 3 步：优先迁入最核心文件

优先级最高：
1. source_snapshot/gateway/platforms/qqbot.py
   这是 QQ Bot 适配器主体，没有它基本不可能跑通。

2. source_snapshot/gateway/config.py
   要保证 Platform.QQBOT、环境变量读取、home channel 等配置能力存在。

3. source_snapshot/gateway/run.py
   要保证 gateway 能创建 QQBotAdapter，并处理相关运行逻辑。

4. source_snapshot/hermes_cli/tools_config.py
   要保证 qqbot 已注册到 PLATFORMS，否则可能报 KeyError: 'qqbot'。

5. source_snapshot/toolsets.py
   要保证 hermes-qqbot 工具集存在，并被 hermes-gateway 收纳。


第 4 步：迁入其余配套文件

继续迁入：
- source_snapshot/tools/send_message_tool.py
- source_snapshot/gateway/channel_directory.py
- source_snapshot/hermes_cli/gateway.py
- source_snapshot/hermes_cli/status.py
- source_snapshot/cron/scheduler.py
- source_snapshot/agent/prompt_builder.py

说明：
这些文件看起来不像“核心连接代码”，但它们补齐了：
- 直接发消息
- channel 枚举
- gateway setup 引导
- CLI 状态显示
- cron deliver 目标识别
- 平台提示词

如果缺失，通常不会一开始就爆掉，但后续很容易出现“部分功能正常、部分功能缺失”的隐性问题。

-----------------------------------
五、建议迁移方式
-----------------------------------

推荐方式：人工 diff 合并，不建议整文件无脑覆盖。

原因：
- 目标 Hermes 可能有自己的本地改动
- 直接覆盖容易把别的平台支持也覆盖掉
- 最稳妥的是：以 source_snapshot 为参考，将 qqbot 相关块合并进目标仓库

推荐操作方法：
1. 用 diff 工具逐文件比对
2. 提取 qqbot 相关新增块
3. 合并到目标代码
4. 每合并 1~2 个核心文件就运行一次最小验证

如果目标仓库非常旧、且与你当前成功环境差异很小，也可以先整文件替换，再做回归测试。

-----------------------------------
六、需要特别注意的关键代码点
-----------------------------------

1. gateway/platforms/qqbot.py
必须提供：
- token 刷新
- gateway URL 获取
- websocket 连接与重连
- heartbeat
- 收消息
- 发消息
- C2C / 群 @ 场景处理

这是最关键的 QQ Bot 运行时代码。

2. hermes_cli/tools_config.py
必须保证：
- PLATFORMS 中有 qqbot
- default_toolset 指向 hermes-qqbot

否则典型报错：
- KeyError: 'qqbot'

3. toolsets.py
必须保证：
- 有 hermes-qqbot
- hermes-gateway includes 中包含 hermes-qqbot

4. gateway/run.py
必须保证：
- 创建平台适配器时能识别 Platform.QQBOT
- 能 import QQBotAdapter
- requirements 不满足时能给出警告
- 能继续走 gateway 运行逻辑
- /sethome 后续逻辑可用

5. gateway/config.py
必须保证：
- Platform 枚举里有 QQBOT
- 支持读取 QQBOT_APP_ID / QQBOT_TOKEN / QQBOT_SECRET
- 支持 QQBOT_HOME_CHANNEL 等可选项

6. tools/send_message_tool.py
必须保证：
- platform_map 中有 qqbot
- 可路由到 _send_qqbot

7. cron/scheduler.py
必须保证：
- cron delivery target 白名单里有 qqbot

-----------------------------------
七、配置方式
-----------------------------------

方式 A：写 config.yaml

把 templates/config.qqbot.template.yaml 中的内容合并到目标机的：
~/.hermes/config.yaml

示例：
platforms:
  qqbot:
    enabled: true
    extra:
      app_id: "YOUR_APP_ID"
      secret: "YOUR_CLIENT_SECRET"

说明：
- 这是本次成功环境中确认有效的方式
- 不要把真实值写入共享文档

方式 B：写环境变量

把 templates/qqbot.env.template 中的变量，按目标环境写入：
~/.hermes/.env
或系统环境变量中。

注意：
从当前成功环境代码看，某些逻辑会检查：
- QQBOT_APP_ID
- QQBOT_SECRET
- QQBOT_TOKEN

因此如果目标代码走环境变量方式，最好三个都配齐。

-----------------------------------
八、Python 依赖
-----------------------------------

根据 qqbot 适配器代码，需要至少安装：
- websockets
- httpx

安装：
pip install websockets httpx

如果 Hermes 跑在 venv 中，请在对应虚拟环境内安装。

-----------------------------------
九、部署与验证顺序
-----------------------------------

1. 合并代码
2. 安装依赖
3. 写 config.yaml 或环境变量
4. 重启 gateway
5. 在 QQ 中发消息测试
6. 若看到：
   No home channel is set for Qqbot
   说明基础链路已经通了
7. 在 QQ 中发送：
   /sethome
8. 再次测试对话

-----------------------------------
十、macOS 上重启 gateway
-----------------------------------

如果使用 launchd 托管：
launchctl stop ai.hermes.gateway && sleep 2 && launchctl start ai.hermes.gateway

说明：
- 改完代码后必须重启
- 改完配置后也必须重启

-----------------------------------
十一、成功判定标准
-----------------------------------

以下都满足，说明迁移成功：
1. 目标 Hermes 启动时不再因为 qqbot 缺失而报错
2. gateway 能创建 QQBotAdapter
3. QQ 中给机器人发消息后能收到回复
4. 不再出现 KeyError: 'qqbot'
5. /sethome 可正常设置当前会话为 home channel
6. 后续 cron / send_message 等涉及 qqbot 的能力可用

-----------------------------------
十二、常见失败原因
-----------------------------------

1. 只复制了 qqbot.py，没有复制其它配套代码
结果：
- 平台入口可能缺失
- toolset 可能缺失
- send_message / cron / 状态展示可能不兼容

2. 只写了 config.yaml，没有迁代码
结果：
- 几乎一定跑不通

3. tools_config.py 没补 qqbot
结果：
- 容易出现 KeyError: 'qqbot'

4. 没安装 websockets/httpx
结果：
- 适配器 requirements check 失败

5. 改完没重启 gateway
结果：
- 旧进程仍运行旧代码

6. 凭据正确但没 /sethome
结果：
- 能收发一部分消息，但 home channel 相关能力未完成初始化

-----------------------------------
十三、关于“是否用了 GitHub 上的 qqbot 代码”
-----------------------------------

本迁移包里的代码来源是：
- 当前这台已验证成功的 Hermes 本地代码快照

它可能在历史上参考过：
- QQ 官方开放平台文档
- 相关 GitHub 项目
- 既有网关平台实现模式

但对新的 Hermes 来说，最可靠的迁移方式不是“让 AI 根据文档重新猜代码”，而是：
- 直接使用本迁移包中的代码快照作为参考或移植来源

也就是说：
你现在交付给另一套 Hermes 的，不再只是经验，而是“可复用的实现依据”。

-----------------------------------
十四、推荐给执行迁移的 AI/工程师的指令
-----------------------------------

请按以下原则执行：
1. 目标仓库原本没有 qqbot 支持。
2. 以本目录 source_snapshot 为参考实现，把 qqbot 相关能力合并进目标 Hermes。
3. 不要只改配置；必须先迁入源码支持。
4. 不要输出或提交任何真实 QQ 密钥。
5. 完成迁移后，使用模板配置填入真实凭据，在目标环境重启 gateway 并测试。
6. 若出现 “No home channel is set for Qqbot”，在 QQ 中执行 /sethome。
7. 最终交付时，输出一份不含密钥的迁移与验证报告。

-----------------------------------
十五、最终结论
-----------------------------------

如果另一套 Hermes 代码库原本没有 qqbot 支持，那么要顺利跑通 qqbot，必须同时具备：
- 文档
- 源码快照/代码迁移依据
- 配置模板
- 依赖安装
- gateway 重启与 QQ 内验证步骤

本目录就是为这个目标准备的完整迁移包。
