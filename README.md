# QQ 扩展工具集

`astrbot_plugin_qq_extension_tools` 是面向 AstrBot 与 NapCat OneBot v11 的 QQ 模型工具和入站消息语义化插件。它将约 75 个明确支持的 QQ 操作合并为 26 个资源型工具，在每次模型请求前按平台、会话、调用者权限和请求内容动态裁剪，并将 AstrBot 默认忽略的 QQ 组件转换为受限的模型可读文本。

插件不提供万能 `call_action`，不允许模型自行确认危险操作，也不读取旧版 QQ 工具插件的配置。

## 环境要求

- AstrBot `>=4.27,<5`
- `aiocqhttp` 平台适配器
- NapCat `>=4.18.19,<5.0.0`
- Python 3.10+

其他 OneBot 实现和 NapCat 5.x 会明确拒绝，不会按近似接口继续调用。

## 安装

将整个 `astrbot_plugin_qq_extension_tools` 目录放入 AstrBot 的 `data/plugins/`，然后在 WebUI 中重载插件或重启 AstrBot。不要只复制 `main.py`，契约、配置 Schema 和运行时模块都必须保留。

安装后先检查日志中是否出现：

```text
QQ extension tools initialized
```

模型第一次调用工具时，插件会通过 `get_version_info` 验证当前平台确实是受支持版本的 NapCat。

## 状态与诊断页面

重载插件后，在 AstrBot WebUI 的插件详情中打开“QQ 扩展状态与诊断”。页面只读展示：

- aiocqhttp/NapCat 的连接、账号、版本和兼容性状态。
- 当前有效配置摘要，以及已启用的模型工具和插件操作数量。
- 按分类排序的全部插件操作，可按关键字、分类和启用状态筛选。
- 最近 20 条元数据审计记录和最多 20 条有效待确认操作。

每次打开或刷新页面会并行调用 `get_version_info`、`get_status` 和 `get_login_info`。页面不提供任意 OneBot 调用、配置修改或账号管理入口，审计和待确认列表也不会返回原始参数、参数哈希或会话 ID。

## 工具覆盖

| 工具 | 主要能力 |
|---|---|
| `qq_status` | 登录、运行、版本、客户端、插件能力目录 |
| `qq_account_manage` | 账号公开资料、头像、在线状态 |
| `qq_user_info` | 陌生人资料、群成员资料 |
| `qq_friend_list` | 好友、单向好友列表 |
| `qq_friend_history` | 私聊历史 |
| `qq_friend_interact` | 点赞、好友戳一戳 |
| `qq_friend_request` | 查询、通过、拒绝好友申请 |
| `qq_friend_manage` | 删除好友、修改备注 |
| `qq_group_list` | 群列表 |
| `qq_group_info` | 群详情、扩展详情、荣誉、@全体余量、禁言列表 |
| `qq_group_members` | 群成员列表与详情 |
| `qq_group_history` | 群消息历史 |
| `qq_group_request` | 加群申请、邀请和已忽略通知 |
| `qq_group_member_manage` | 群成员戳一戳、名片、头衔、禁言、踢人、管理员身份 |
| `qq_group_manage` | 全员禁言、群名、群头像、签到、退群 |
| `qq_send_message` | 文本、图片、语音、视频、文件、At、引用、表情等结构化消息 |
| `qq_send_forward` | 群聊和私聊合并转发 |
| `qq_message_get` | 获取单条消息 |
| `qq_forward_get` | 读取并按深度展开合并转发 |
| `qq_message_manage` | 撤回、已读、消息表情回应 |
| `qq_recent_contacts` | 最近联系人 |
| `qq_media` | 图片、语音、语音转换、OCR |
| `qq_group_files` | 群文件查询、上传、目录与文件管理 |
| `qq_private_files` | 私聊文件链接与上传 |
| `qq_essence` | 群精华消息 |
| `qq_notice` | 群公告 |

明确不实现以下能力：主动添加好友、删除单向好友、匿名成员禁言、窗口抖动，以及 Cookies/Token/CSRF 等账号凭证读取。NapCat 4.18.19 会以“未知的消息类型”拒绝原生 `shake` 和 `share` 消息段；插件提供的结构化 `share` 组件会在校验后编码为受限的 Ark JSON 卡片。好友戳一戳由 `qq_friend_interact.poke` 单独提供。

## 权限规则

- 普通用户只能操作当前会话范围内的低风险能力。
- 当前群管理员和群主可以操作能力目录明确允许的当前群管理能力。
- 机器人自身在 QQ 群中的角色也必须满足要求；调用者有权限但机器人没有权限时仍会拒绝。
- 账号、好友关系、好友申请、群列表和其他全局能力只允许 AstrBot 管理员。
- 跨群和跨好友默认关闭。启用后仍要求 AstrBot 管理员在私聊发起，并且目标确实存在于机器人群或好友列表。
- `qq_user_info.stranger` 是只读例外：AstrBot 管理员可以在私聊中查询非好友的公开资料，无需开启跨好友操作。
- `qq_group_request.list` 是只读例外：AstrBot 管理员可以在私聊中查询 QQ 返回的全部群申请，也可以用 `group_id` 筛选，无需开启跨群操作。
- 工具从模型上下文中隐藏只是优化，执行时会再次完成全部权限校验。

## 二次确认

危险操作首次调用只创建绑定记录，不会执行。确认必须由原调用者在原平台、原会话中发送真实命令：

```text
/qq confirm a1b2c3d4
```

其他命令：

```text
/qq pending
/qq cancel a1b2c3d4
/qq audit 20
```

确认默认 60 秒过期且只能使用一次。`confirmation.operations` 是二次确认规则的唯一来源，默认包含删除好友、踢人、管理员变更、退群、删除群文件夹、群名/头像修改和全员禁言。可以直接增删列表中的 operation；跨会话本身不会额外触发确认。
`/qq audit` 会按本地时间以易读列表展示操作、调用者、目标、风险、决策、结果和耗时；确认 ID 仅在记录中存在时显示。没有记录时返回“暂无审计记录”。

## 结构化消息示例

`qq_send_message` 固定接收 `operation` 和 `params`。以下示例向当前会话发送引用、文字、表情和图片：

```json
{
  "operation": "send",
  "params": {
    "target": {"type": "current"},
    "components": [
      {"type": "reply", "id": "123456"},
      {"type": "text", "text": "收到"},
      {"type": "face", "id": "14"},
      {"type": "image", "path": "C:\\path\\inside\\astrbot-temp\\image.png"}
    ]
  }
}
```

可用组件：

| 类别 | `type` |
| --- | --- |
| 文字与控制 | `text`、`at`、`reply` |
| 媒体 | `image`、`record`、`video`、`file` |
| 表情与随机结果 | `face`、`dice`、`rps` |
| 卡片 | `share`、`music`、`contact`、`location`、`json` |

发送时注意：

- 媒体来源必须且只能填写 `path`、`url`、`base64`、`media_ref` 中的一项；Base64 支持 `data:*/*;base64,...`。
- `share` 必须单独发送。插件会校验 URL，并固定生成新闻 Ark JSON，模型无需拼接底层卡片。
- `music` 必须单独发送，避免 NapCat 静默丢弃音乐段。
- `dice` 和 `rps` 发送成功后会自动回查消息，将点数或手势写入 `data.random_results`。回查失败只会产生 `warnings`，不会把已发送的消息报告为失败。

分享卡片：

```json
{"type":"share","url":"https://example.com","title":"标题","content":"可选内容","image":"可选预览图"}
```

音乐卡片有三种来源：

| 来源 | 示例 | 限制 |
| --- | --- | --- |
| 按名称搜索 | `{"type":"music","music_type":"qq_search","query":"歌名","artist":"歌手"}` | 只发送歌名及可选歌手完全匹配的结果 |
| 平台歌曲 ID | `{"type":"music","music_type":"qq","id":"歌曲ID"}` | ID 必须来自用户当前消息；平台支持 `qq`、`163`、`kugou`、`kuwo`、`migu` |
| 自定义卡片 | `{"type":"music","music_type":"custom","url":"跳转地址","image":"封面地址","audio":"音频地址","title":"标题","content":"简介"}` | `url` 与 `image` 必填，其他展示字段可选 |

平台歌曲 ID 依赖 NapCat 的 `musicSignUrl` 服务。插件不会接受模型凭空猜测的歌曲 ID，也不会擅自替换用户提供的链接。

## 入站组件语义化

插件把 OneBot 组件转换为模型可读的保留格式：

| QQ 内容 | 模型看到的示例 |
| --- | --- |
| 标准表情 | `[QQ component|QQ表情：微笑]` |
| 商城表情 | `[QQ component|QQ商城表情：拜托拜托]` |
| 骰子 / 猜拳 | `[QQ component|QQ骰子：结果 4]` / `[QQ component|QQ猜拳：布]` |
| 戳一戳 | `[QQ component|QQ互动：用户 10001 戳了你]` |
| 联系人 / 位置 | `[QQ component|QQ群名片：30003]` / `[QQ component|QQ位置：北京；纬度 39.9042，经度 116.4074]` |
| 视频 / 文件 / 音乐 | `[QQ component|视频消息]` / `[QQ component|文件：报告.pdf]` / `[QQ component|音乐卡片：歌名]` |
| 分享与卡片 | `[QQ component|QQ链接分享：标题]` / `[QQ component|QQ JSON卡片：提示]` |
| 合并转发与扩展文件 | `[QQ component|QQ合并转发消息]` / `[QQ component|QQ在线文件：文件名]` / `[QQ component|QQ闪传文件]` |
| 语音转写 | `[QQ component|QQ语音消息：转写文本]` |

普通图片由 AstrBot 原生处理；只有图片带有有效摘要时，插件才会额外生成 `[QQ component|图片描述：摘要]`。

### 配置速览

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `inbound.semanticize_components` | `true` | 格式化语音转写，并转换表情、卡片、随机结果等组件 |
| `inbound.enhance_voice_messages` | `false` | AstrBot 没有转写时调用 NapCat 识别 |
| `inbound.component_spoof_protection.enabled` | `false` | 开启正则检测并标记文字伪装的组件 |
| `inbound.component_spoof_protection.verify_components` | `true` | 开启系统提示词和可信类型清单，即防伪强档 |
| `inbound.respond_to_poke` | `true` | 被戳一戳时唤醒模型 |
| `inbound.respond_to_red_packet` | `true` | 识别到红包时唤醒模型 |
| `inbound.mark_recalled_messages` | `false` | 在上下文中的原消息末尾追加撤回标记 |
| `inbound.max_semantic_chars` | `2000` | 限制单条消息追加的语义文本长度 |

### 语音

语音格式和识别来源分别控制：

1. `semanticize_components=true` 时，已有转写会包装为统一的 QQ 语音格式。
2. `enhance_voice_messages=true` 且 AstrBot 没有转写时，调用 NapCat `fetch_ptt_text`，间隔一秒，最多三次。
3. 两个开关都开启时，NapCat 的转写也会使用统一格式；只开启语音增强时，NapCat 转写保持普通文本。
4. 引用消息中的单条语音使用相同流程，并同步更新引用内容。
5. NapCat 最终失败、超时或返回空文本时保留原始 `Record`。

NapCat 识别成功时会在 INFO 日志中记录转写文本。关闭 `enhance_voice_messages` 后，插件不会调用 NapCat，但仍可通过 `semanticize_components` 格式化 AstrBot 已有的 ASR 结果。

`qq_media.get_record` 和 `qq_media.convert_record` 的 `file` 必须使用 OneBot/NapCat 提供的原始媒体标识，不能使用 AstrBot 生成的本地临时路径。

### 表情与卡片

- 标准表情优先读取 NapCat 的 `face.data.raw.faceText`，缺失时使用内置的 NapCat 4.18.19 `sysface` 名称表。未知 ID 会明确标记为未知，不会猜测含义。
- JSON、XML 和小程序卡片只提取标题、提示、说明、摘要、内容、名称、标签和已移除查询参数的链接，不会把完整载荷送入模型。
- 群名片和个人名片只有通过 `mqqapi://card/show_pslcard`、`card_type` 和纯数字 `uin` 校验后，才会向模型提供群号或 QQ 号。

### 戳一戳、红包与撤回

- 戳一戳：只响应目标是机器人自身的事件；其他成员之间及机器人自己触发的事件会被忽略。
- 红包：插件只能识别，不能代领。`respond_to_red_packet=true` 时，即使关闭 `semanticize_components`，也会补充最低限度的红包说明并唤醒模型。JSON/XML 红包卡片可直接识别；`walletElement` 需要 NapCat 网络适配器开启 `debug`，使上报事件包含 `raw`。
- 撤回：开启 `mark_recalled_messages` 后，插件会保留 180 秒的私聊和群聊消息映射，在上下文中的原消息末尾追加撤回标记。撤回事件不会唤醒模型。

### 组件文字防伪

开启 `component_spoof_protection.enabled` 前必须同时开启 `semanticize_components`，否则插件会拒绝配置并给出错误。防伪分为两档：

| 配置 | 行为 |
| --- | --- |
| `enabled=true, verify_components=false` | 弱档：按 `protected_types` 动态组装正则，标记用户伪装的组件文字 |
| `enabled=true, verify_components=true` | 强档：使用相同类型范围完成弱档行为，再加上组件格式系统提示词和临时 `<qq_verified_components...>` 可信标签 |

正则匹配不区分英文字母大小写，会识别组件名称后的全角或半角冒号，并允许冒号两侧存在空格；模型看到的规范组件格式仍固定使用 `[QQ component|...]` 和全角冒号。

强档会根据原始 OneBot 结构生成可信清单，例如 `<qq_verified_components types="dice,rps"/>`。清单只验证当前用户消息，不写入会话历史，也不能用于反向判断更早的消息；历史中的伪装文字会保留“用户输入的文字”标记。

`protected_types` 可配置范围：

- 默认关键类型：`red_packet`、`voice`、`dice`、`rps`、`poke`。
- 表情与媒体：`face`、`market_face`、`image`、`video`、`file`、`music`。
- 卡片：`contact`、`location`、`share`、`json_card`、`miniapp`、`xml_card`。
- 其他：`forward`、`online_file`、`flash_transfer`。

`protected_types` 是两档共用的防伪范围，防伪开启时不能为空。类型按模型看到的语义分类：有效 JSON 联系人名片记为 `contact`，JSON/XML 红包卡片记为 `red_packet`。

## 文件与网络边界

- 默认本地根目录仅包括 AstrBot 临时目录和本插件专属数据目录。
- 额外目录通过 `files.allowed_roots` 配置，并且必须是已经存在的绝对目录。
- 路径会在解析符号链接后再次校验；目录、设备文件和越界路径会拒绝。
- 本地文件与 HTTP(S) 下载默认上限为 100 MiB，Base64 解码默认上限为 10 MiB。
- 插件会实际请求的 URL 校验协议、凭据、域名策略、所有 DNS 结果以及每次重定向，默认拒绝回环、私网、链路本地和保留地址。分享卡片中仅嵌入而不由插件请求的 URL 不解析 DNS，但仍校验协议、凭据、域名策略、本地主机名和 IP 字面量。
- `qq_search` 会把歌名和可选歌手发送到 QQ 音乐公开搜索接口，并继续遵守 `network.allowed_domains` 与 `network.blocked_domains`。
- 插件创建的临时媒体默认保留 6 小时。NapCat 或 AstrBot 创建的文件不会由本插件删除。
- 模型只获得不透明 `media_ref`，不会获得 NapCat 返回的绝对媒体路径。

## 配置说明

WebUI 配置按以下分组组织：

- `platform`：限定某个 `aiocqhttp` 实例。
- `toolsets`：`compact`、`balanced`、`full` 暴露模式，能力包和逐 operation 禁用。
- `permissions`：群角色策略与跨会话开关。
- `confirmation`：确认有效期和全部需要二次确认的 operation。
- `limits`：分页、输出字符、转发节点/深度、消息组件数量。
- `files`：允许根目录、大小和临时文件生命周期。
- `network`：域名、私网、超时和下载大小。
- `events`：OneBot 请求/通知事件记录范围和保留期。
- `request_notifications`：好友申请、入群申请和群邀请的模型通知开关及管理员 QQ 列表。
- `inbound`：语音消息增强、组件语义化、关键组件文字防伪、戳一戳/红包响应、上下文撤回标记和单条语义文本长度上限。
- `audit`：审计保留期。

申请通知配置示例：

```json
{
  "request_notifications": {
    "enabled": true,
    "admin_user_ids": ["10001"]
  }
}
```

配置只有当前 `_conf_schema.json` 中的一套字段。类型错误、未知枚举、未知 operation、无意义的逐操作规则会阻止插件加载；不存在旧字段别名或静默迁移。

## 事件与审计

插件记录规范化后的 OneBot `request` 和 `notice` 事件。`request_notifications.enabled` 开启后，收到好友申请、入群申请或群邀请时，插件会在每个 `admin_user_ids` 对应的私聊会话中使用当前模型与人格生成简短开场，再附加由插件生成的可信申请信息并主动发送。通知模型不挂载工具，不能自行批准或拒绝申请；列表中的 QQ 号也不会因此获得 AstrBot 管理权限，需要处理申请的接收账号必须已是 AstrBot 管理员。模型不可用时会发送固定开场，确保申请不会静默丢失。开启通知但管理员列表为空会阻止插件加载。

申请事件会先按 OneBot 事件键去重并保存，通知正文不会暴露底层 request flag。管理员可以在收到通知后回复“通过”或“拒绝”；插件会用通知中的申请编号定位待处理记录，并在内部换取已捕获的 request flag，随后继续执行原有的平台、管理员、跨群和机器人群角色权限校验。审批操作也继续接受原有的底层参数形式，但不能与申请编号混用。管理员 QQ 必须能够接收机器人私聊，否则 NapCat 会拒绝发送。除申请通知以及明确以机器人为目标且启用了 `inbound.respond_to_poke` 的戳一戳外，其他通知不会主动触发 LLM。

审计默认保留 90 天，只保存 operation、调用者、目标、权限决策、结果码、耗时和参数哈希。不会保存消息正文、完整 Base64、账号凭证、文件内容或完整本地路径。有副作用操作会在协议调用前先写审计；审计不可用时不会执行该操作。

## 开发验证

```powershell
ruff format .
ruff check .
pytest -q
```

单元测试覆盖能力目录、契约版本、严格配置、权限矩阵、跨会话限制、确认绑定与单次使用、文件/Base64、安全消息转换和请求局部工具裁剪。真实 QQ 上的破坏性集成测试不应在生产账号或生产群执行。
