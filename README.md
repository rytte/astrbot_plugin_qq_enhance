# ✨ QQ 能力增强

让 AstrBot 通过自然语言操作 QQ，也能读懂 QQ 特有的消息与互动。

`astrbot_plugin_qq_enhance` 面向 **AstrBot + NapCat OneBot v11**，提供 **29 个模型工具、81 个操作**，覆盖消息发送、好友互动、群管理、文件处理与申请审批；同时将表情、戳一戳、卡片和语音转写整理成模型可理解的内容。

工具会根据平台、会话、调用者权限和请求内容动态选择。指定操作需要用户发送确认命令后才会执行。

[功能亮点](#features) · [快速开始](#quick-start) · [常用配置](#configuration) · [权限与确认](#permissions) · [常见问题](#faq) · [详细参考](#reference) · [开发验证](#development)

<a id="features"></a>

## 🌟 功能亮点

### 🛠️ QQ 操作工具（NapCat API 封装）

将 NapCat 的 QQ 操作封装为模型可调用的工具，通过自然语言完成消息互动、好友管理和群聊操作。

> 支持精简、平衡、完整三种工具暴露模式，默认使用平衡模式，按会话、权限和请求内容选择工具，减少模型上下文占用。

| 能力 | 可以做什么 |
| --- | --- |
| 消息与互动 | 发送文字、图片、语音、视频、文件与卡片，使用引用、At、表情、骰子、猜拳、戳一戳和合并转发 |
| 好友与账号 | 查询资料、点赞、修改备注、管理好友申请，以及由 AstrBot 管理员维护机器人资料 |
| 群聊管理 | 查询成员、历史消息和公告，管理禁言、群名片、精华消息、群申请与群文件 |

完整的 NapCat 动作对应关系见 [能力矩阵](./Capabilities.md)。

### 🧩 插件增强能力

围绕消息理解、事件响应和工具调用提供的增强功能。

| 能力 | 可以做什么 |
| --- | --- |
| 消息感知 | 理解 QQ 表情、商城表情、卡片和随机结果，在上下文中标记撤回消息 |
| 消息响应 | 收到表情、卡片、戳一戳、红包等组件时，可唤醒模型回复 |
| 消息防抖 | 连续输入时取消尚未产生回复的生成，将前条完整输入保存为独立用户历史，保留附件和撤回定位，支持全部消息类型 |
| 图片引用 | 图片保存为历史上下文时替换为轻量引用并提供工具，需要时模型可按需查看历史图片 |
| 跨会话交流 | 跨会话发送消息后，将发送内容和来源说明写入目标会话历史，并能够接收回复 |
| 语音识别 | AstrBot 未生成语音转写时，自动调用 NapCat 补充识别 |
| 组件防伪 | 标记用户用普通文字伪装的红包、语音、骰子等组件，并根据真实消息结构提供可信类型清单，帮助模型区分真实组件与伪装文字 |
| 网页阅读 | 安全读取公开网页、按行续读和页内查找，网页快照按原调用者与会话隔离 |
| 事件通知 | 可将好友申请、入群申请和群邀请私聊通知指定管理员账号 |
| 管理与诊断 | 按权限开放工具，支持操作确认、审计记录，以及 WebUI 状态与诊断页面 |

例如，收到真实的 QQ 骰子、表情或语音时，模型可以看到这样的内容：

```text
[QQ component|QQ骰子：结果 4]
[QQ component|QQ表情：微笑]
[QQ component|QQ语音消息：我们下午三点见]
```

这些是插件生成的语义示例。

### 🎯 插件设计理念

> [!Note]
>
> **目标：让 QQBot 真正参与 QQ 交流**
>
> 我希望这个插件不只是给 QQBot 增加一组可以调用的 API，而是让它更接近一个真正使用 QQ、理解 QQ，也能自然参与交流的人。它应该看懂表情、引用、语音、卡片和各种互动，也能发图片、回复消息、戳一戳、管理群聊，并记得对方刚才连续说了什么。
>
> 为此，本插件既提供覆盖消息、好友、群聊、文件和申请处理等场景的 QQ 操作，也补充消息语义化、消息防抖、撤回标记、图片历史轻量化和事件通知等增强能力，让模型从“能调用 QQ 接口”进一步变成“能在 QQ 中连贯地与人交流”。
>
> **为什么把增强功能放在一起**
>
> 这些功能共同参与一条完整的消息处理链路，并不是为了单纯堆叠功能。例如：
>
> - 防抖需要保留每条连续输入的完整内容，撤回标记则必须定位到防抖过程中已经写入历史的原消息。
> - 图片需要在当前轮保留原始视觉信息，同时避免在后续历史中长期占用大量上下文。
> - QQ 特有组件需要转换为模型可读语义，同时防止普通文字伪装成真实组件。
>
> 统一协调这些环节，才能让消息顺序、附件、撤回状态、会话归属和模型上下文保持一致，避免多个互不知情的插件分别修改同一条消息。
>
> **安全也是自然交互的一部分**
>
> 更像真人并不意味着不受约束。越丰富的 QQ 操作能力，越需要明确的安全边界。本插件同时提供：
>
> - 会话与平台隔离、调用者权限检查、敏感操作二次确认；
> - 工具按需暴露、参数与路径校验、网络访问限制；
> - 操作审计，让重要操作可确认、可追踪、可拒绝。
>
> 自然、连贯和安全不是彼此独立的附加项，而是这个插件希望一起解决的问题。

<a id="quick-start"></a>

## 🚀 快速开始

### 1. 准备环境

| 项目 | 要求 |
| --- | --- |
| AstrBot | `>=4.27,<5` |
| 平台适配器 | `aiocqhttp` |
| QQ 协议端 | NapCat `>=4.18.19,<5.0.0`，使用 OneBot v11 |
| 模型 | 在 AstrBot 中配置支持工具调用的模型，并为目标会话启用模型对话 |

先确认 AstrBot 与 NapCat 已连接，机器人能够正常收发 QQ 消息。插件执行工具时会校验协议端实现与版本；其他 OneBot 实现及 NapCat 5.x 不在当前支持范围内。

### 2. 安装插件

在 AstrBot WebUI 的插件管理中，使用以下仓库地址安装：

```text
https://github.com/rytte/astrbot_plugin_qq_enhance
```

也可以将完整的 `astrbot_plugin_qq_enhance` 仓库目录放入 AstrBot 的 `data/plugins/`，然后重载插件或重启 AstrBot。

初始化成功时，日志会出现：

```text
QQ Enhance initialized
```

### 3. 试着说一句

按当前会话的唤醒方式与机器人对话，例如在群聊中先 @ 机器人，再发送下面的请求。模型会根据请求选择工具，通常无需手写工具参数。

| 场景 | 示例请求 |
| --- | --- |
| 群聊或私聊 | “发一个骰子。” |
| 与机器人好友私聊 | “给我点个赞。” |
| 当前群聊 | “查看本群公告。” |
| 当前群聊 | “列出本群根目录的文件。” |
| AstrBot 管理员私聊 | “查看待处理的好友申请。” |

群管理操作还需要满足调用者和机器人自身的群权限，具体见 [权限与确认](#permissions)。

### 4. 查看运行状态

在 AstrBot WebUI 的插件详情中打开 **“QQ 能力增强状态与诊断”**，可查看 NapCat 连接、登录账号、版本兼容性、有效配置摘要、启用能力、近期审计及待确认操作。能力列表支持搜索和筛选。

页面为只读；每次打开或刷新会查询 NapCat 的版本、运行状态和登录信息。

<a id="configuration"></a>

## ⚙️ 常用配置

在 AstrBot WebUI 的插件配置中调整。下文的 **WebUI 初始值** 来自当前 [_conf_schema.json](./_conf_schema.json)；已有安装以实际保存的配置为准。

### 工具暴露模式

工具暴露模式决定每次请求向模型提供哪些 QQ 工具。通过 `toolsets.exposure_mode` 配置，WebUI 初始为 `balanced`。

精简和平衡模式会为群聊、私聊选择相应的常用工具，再根据请求中的关键词补充相关工具，优先保留与请求匹配的能力。例如，在群聊中请求“查看本群公告”时，会优先选入群公告工具。这样可以减少工具描述占用的上下文，让模型更容易关注当前任务所需的能力。

| 模式 | 选择方式 | 适用场景 |
| --- | --- | --- |
| `compact`（精简） | 常用工具加上请求匹配的工具，每次最多保留 10 个 QQ 工具 | 希望进一步减少工具上下文占用 |
| `balanced`（平衡） | 在按需选择的基础上，为 AstrBot 管理员补充好友或群列表、最近联系人等工具，每次最多保留 15 个 QQ 工具 | 日常使用，兼顾常用能力与上下文占用 |
| `full`（完整） | 保留当前会话与权限筛选后可见的全部 QQ 工具 | 需要更广的工具选择范围，或排查按需选择未覆盖的请求 |

上述数量仅指本插件的 QQ 工具。裁剪只对当前模型请求生效，后续请求会重新选择，不会永久关闭某个工具。完整模式仍受权限与启用范围约束，执行时也会再次校验权限。

还可通过 `toolsets.enabled_packs` 限定能力包，留空表示启用全部能力包；通过 `toolsets.disabled_operations` 按操作禁用能力，例如 `qq_group_manage.leave`。这两项配置对三种模式均生效。

### 消息感知与响应

| 配置 | WebUI 初始值 | 作用 |
| --- | --- | --- |
| `inbound.semanticize_components` | `true` | 将 QQ 特有组件和已有语音转写整理为模型可读文本 |
| `inbound.enhance_voice_messages` | `true` | AstrBot 没有语音转写时，尝试使用 NapCat 识别，支持当前消息及引用中的单条语音 |
| `inbound.component_spoof_protection.enabled` | `true` | 标记用户用普通文字伪装的 QQ 组件 |
| `inbound.component_spoof_protection.verify_components` | `true` | 防伪开启时，额外提供真实组件类型清单与系统提示词 |
| `inbound.respond_to_poke` | `true` | 被其他用户戳一戳时唤醒模型 |
| `inbound.respond_to_red_packet` | `true` | 识别到红包时唤醒模型；支持识别，不能代领 |
| `inbound.mark_recalled_messages` | `true` | 在上下文中的原消息末尾追加撤回标记 |
| `inbound.max_semantic_chars` | `2000` | 限制单条消息追加的语义文本长度 |

组件防伪依赖 `semanticize_components=true`。需要关闭组件语义化时，请同时关闭 `component_spoof_protection.enabled`，否则配置校验会阻止插件加载。

### 图片历史轻量化

此功能默认开启；将 `context_images.enabled` 设为 `false` 后，不再归档新图片、改写图片历史或开放 `qq_media.inspect`，已有图片副本保持不变。收到 QQ 图片时，插件会把未经重新编码的原图复制到插件数据目录。当前 Agent 运行仍保留 AstrBot 已准备的图片路径提示和推理图片；保存历史时会同时过滤路径提示与图片 Base64，只留下如下引用：

```text
[QQ ImageRef image_ref=img_a1b2c3..., 1920x1080；如需重新查看原图，调用 qq_media(operation="inspect", params={"image_ref":"img_a1b2c3..."})]
```

`qq_media.inspect` 只接受当前平台实例、消息来源和 AstrBot 会话共同绑定的引用，不能跨群、跨私聊或跨会话读取。重载的图片只在当次 Agent 工具循环中可见；AstrBot 在该轮生成的工具缓存路径、图片 Base64 和当前消息的附件路径提示都会在保存历史前移除。

插件启动后立即检查一次图片生命周期，之后每个主机本地自然日最多检查一次。引用从历史消失后进入孤儿宽限期，默认在日期相差 3 天后删除；重新出现则取消孤儿标记。所有原图默认最多保留 30 个自然日，无论是否仍被历史引用；将 `context_images.retention_days` 设为 `0` 可关闭此绝对保留期，但孤儿与容量清理仍然生效。

原图默认总容量为 2048 MiB。归档新图片时空间不足，会从最早的本地自然日开始整日淘汰，无论图片是否仍被历史引用，并按日期继续清理到整批新图片可以写入。若当前批次本身超过总容量，则拒绝归档且不淘汰已有图片。被清理的引用再次交给 `qq_media.inspect` 时会明确返回图片已过期、不存在或不属于当前会话。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `context_images.enabled` | `true` | 是否启用图片历史轻量化 |
| `context_images.orphan_grace_days` | `3` | 图片引用从历史消失后的自然日宽限天数 |
| `context_images.retention_days` | `30` | 所有原图的最长自然日保留期；0 表示关闭绝对保留期 |
| `context_images.max_storage_mb` | `2048` | 会话原图总存储上限，单位 MiB |

### 跨会话消息衔接

此功能默认开启，可通过 `cross_session_handoff.enabled` 总开关关闭。开启后，模型成功使用 `qq_send_message.send`、`qq_send_forward.send`，或 AstrBot 内置 `send_message_to_user` 向其他普通 QQ 会话发送消息时，插件会把实际发送内容和来源说明追加到目标会话的 `assistant` 历史，不会因此唤醒目标会话模型。关闭后不会追加这类历史。

如需让普通用户通过现有 `qq_send_message.send` 向管理员转达回复，可开启 `permissions.allow_cross_private_to_admin`。该配置默认关闭，并且依赖跨会话消息衔接总开关；开启后只允许私聊同平台、机器人好友列表中的 AstrBot 管理员，不放宽跨群、临时会话、合并转发或其他跨好友操作。来源说明会标明原发起人是否为管理员，实际发送时仍根据 AstrBot 当前 `admins_id` 重新校验目标身份。

来源说明包含发起会话、用户、原话和时间，原话会进入目标会话历史，因此跨会话发送前应确认目标会话可以看到这些信息。插件不保存逐条衔接记录；目标 QQ 实际收到的消息不包含来源说明。

### 消息防抖

防抖默认开启，可通过 `debounce.enabled` 关闭。群聊默认共用防抖，私聊仍按用户隔离；可通过 `debounce.shared_group` 关闭群聊共享。

首条输入会按照 `initial_window_seconds` 等待后进入模型流程。同一会话、同一用户继续输入时，如果前一请求仍可取消，插件会按照 `followup_window_seconds` 等待，再取消它，将该条输入保存为没有机器人回复的独立 `user` 历史消息，并让新输入进入 AstrBot 原有流程。例如：

```text
user：我想去杭州
user：周六出发
user：我上一条发了什么？
assistant：……
```

每条输入保留 AstrBot 实际准备的完整内容和已开启的身份、昵称、时间提醒，不添加消息编号或“尚未回复”的额外提示词。消息 ID 只在插件内部用于撤回定位。前一条在后续模型请求失败时仍保留为独立历史；被取消的模型请求已经消耗的 token 不会退回。

防抖不按消息组件类型设置白名单：文字、引用、图片、语音、文件、视频、合并转发、JSON/XML/小程序卡片、红包、戳一戳、表情、骰子、猜拳、音乐、分享、名片、位置等均复用 AstrBot 和本插件现有的解析结果。语音等耗时预处理不会改变输入的先后顺序。防抖只协调已经能够进入本地 Agent 的输入，不新增组件解码器，也不改变群聊触发规则；红包和戳一戳仍受对应 `inbound` 开关控制，申请通知和撤回通知不会作为新问题进入防抖。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `debounce.enabled` | `true` | 启用消息防抖 |
| `debounce.shared_group` | `true` | 群聊共用防抖；关闭后同一群聊中的不同用户分别处理，私聊始终按用户隔离 |
| `debounce.initial_window_seconds` | `0` | 首条消息进入模型前的等待窗口，0 表示不额外等待 |
| `debounce.followup_window_seconds` | `0` | 后续消息触发取消前的等待窗口，0 表示立即处理 |
| `debounce.max_wait_seconds` | `5` | 一轮防抖实际等待窗口的累计上限，0 表示不限制；模型和工具运行时间不计入 |
| `debounce.max_messages` | `8` | 每批最多续接的输入条数 |
| `debounce.max_buffer_mb` | `32` | 已准备且需要持久化的输入内容预算，单位 MiB；会话图片 Base64 已被排除 |
| `debounce.ignore_prefixes` | `["/", "!"]` | 排除命令类前缀；空列表表示不按前缀排除 |

前一请求开始执行工具、进入流式发送、发送过内容，同一共享会话有其他用户插话，或达到上述预算时，插件会等待该请求结束，再处理后续输入，不截断或丢弃前面的消息。已由其他插件处理的输入沿用原流程。当前支持 AstrBot 本地 Agent；第三方 Agent Runner 不执行此防抖。

撤回会定位到对应的独立用户消息，包括无正文的多媒体输入；防抖开启时也会缓存预处理期间到达的撤回通知。撤回标记只更新本地输入和上下文，不单独触发模型，也无法改变已经发给模型的请求。上下文裁剪、服务商对连续 `user` 消息的转换仍由 AstrBot 和服务商适配器负责。

### 申请通知

需要接收好友申请、入群申请和群邀请通知时，开启 `request_notifications.enabled`，并填写接收账号的 QQ 号。以下是对应配置片段，请替换示例 QQ 号：

```json
{
  "request_notifications": {
    "enabled": true,
    "admin_user_ids": ["10001"]
  }
}
```

通知默认关闭。开启后，机器人会在接收账号的私聊会话中使用当前模型与人格生成开场，再附加申请信息和申请编号。模型不可用时使用固定开场；生成通知时不挂载工具。

接收账号必须能够收到机器人的私聊。需要回复“通过”或“拒绝”来处理申请的账号，还必须已被设为 **AstrBot 管理员**；填写通知名单不会授予权限。开启通知时，名单不能为空。

### 网页阅读

网页阅读提供三个只读工具，支持读取公开网页、按行续读和页内查找。网页通过 HTTP 下载，并使用 Trafilatura 在本地提取正文，无需第三方网页解析 API。使用前需安装 `requirements.txt` 中的依赖。

| 工具 | 参数 | 作用 |
| --- | --- | --- |
| `read_url` | url | 读取公开 HTML 或纯文本，返回正文首段和 page_id |
| `read_page_section` | page_id、start_line=1、line_count=20 | 继续阅读同一份快照，最多请求 100 行 |
| `find_in_page` | page_id、keyword、start_line=1、max_matches=5 | 不区分大小写的字面量查找，最多返回 10 个匹配行及附近正文 |

可直接说“读取这个链接并总结”“继续读”或“在网页里找安装步骤”。工具直接接受表中参数，无需 `operation/params` 包装，可与内置搜索配合使用。

正文按行返回（从 1 开始，每行最多 160 字符），附网址、标题和抓取时间。使用 `page_id` 和 `next_start_line` 续读，返回量受 `limits.max_output_chars` 限制。

网页缓存在内存中，按平台实例、机器人账号、调用者和会话隔离，续读和查找不联网。缓存过期、被淘汰或插件重载后需重新读取；重读同一网址会生成新快照。

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `web_reader.enabled` | `true` | 网页阅读总开关；关闭后隐藏并禁用三个网页工具，不影响内置搜索或 QQ 功能 |
| `web_reader.cache_ttl_seconds` | 900 | 快照有效期（秒） |
| `web_reader.max_cached_pages` | 32 | 全插件最多缓存的网页数 |
| `web_reader.max_cache_mb` | 16 | 缓存容量上限（MiB） |
| `web_reader.max_download_size_mb` | 2 | 单页解压后下载上限（MiB），与 `network.max_download_size_mb` 取较小值 |
| `web_reader.max_text_chars` | 200000 | 单页正文字符上限 |
| `web_reader.max_concurrent_requests` | 2 | 抓取与解析的并发上限 |

抓取与解析共用 `network.timeout_seconds` 超时预算，并发已满时拒绝新请求。

网页工具属于 `web` 能力包。在 `toolsets.disabled_operations` 中填写 `read_url.read`、`read_page_section.read` 或 `find_in_page.find` 可分别禁用。它们不支持二次确认，不能加入 `confirmation.operations`。

仅读取静态正文，不支持 PDF、图片 OCR、登录、验证码、JavaScript 渲染、截图或整站爬取。登录页和动态页面可能无法读全；下载不完整、正文超限或提取失败时返回错误，不以搜索摘要代替原文。网页内容视为不可信资料，不授予 QQ 操作权限。

### 操作范围与保留期

| 配置 | WebUI 初始值 | 作用 |
| --- | --- | --- |
| `platform.platform_id` | 空字符串 | 留空允许任意 `aiocqhttp` 实例；填写后限定该实例 |
| `permissions.allow_group_admin` / `allow_group_owner` | `true` | 允许当前群管理员、群主使用相应群管理能力 |
| `permissions.allow_cross_group` / `allow_cross_private` | `true` | 允许 AstrBot 管理员在校验目标后跨群、跨好友操作 |
| `confirmation.ttl_seconds` | `120` 秒 | 待确认操作的有效期 |
| `network.allow_private_network` | `false` | 允许插件请求私网或其他非公网地址 |
| `events.retention_days` | `15` 天 | 请求与通知事件的保留期 |
| `audit.retention_days` | `30` 天 | 操作审计的保留期 |

完整字段、取值范围与说明见 [_conf_schema.json](./_conf_schema.json)。配置会严格校验字段、类型、枚举和操作名称，错误配置会阻止插件加载。

network.allow_private_network 的 WebUI 和运行时默认值均为 false。更新默认值不会覆盖已经显式保存的 true；已有安装如需禁止私网访问，请在 WebUI 将该项设为 false 后重载插件。

<a id="permissions"></a>

## 🔐 权限与二次确认

### 谁可以操作

| 身份 | 可用范围 |
| --- | --- |
| 普通用户 | 当前会话内允许的查询、发送和互动能力 |
| 当前群管理员 | 配置允许时，使用能力目录授权的当前群管理操作 |
| 当前群群主 | 配置允许时，使用当前群管理及要求群主身份的操作 |
| AstrBot 管理员 | 使用账号、好友关系、申请处理、群列表等全局能力；跨会话操作受对应开关约束 |

执行时还会检查机器人在目标群中的实际角色。调用者有管理权限，机器人也需要满足该操作要求的管理员或群主身份。跨会话操作通常还会核实目标属于机器人的群或好友列表。

两个只读例外：AstrBot 管理员在私聊中查询陌生人公开资料，无需开启跨好友；在私聊中查询全部群申请或按群号筛选，无需开启跨群。两者从群聊发起跨会话查询时，仍受对应开关约束。

工具选择只决定模型能看到哪些工具，执行阶段会再次检查权限。

### 如何确认操作

`confirmation.operations` 决定哪些操作需要二次确认。初始列表包含：删除好友、删除群文件夹、修改群头像、退群、修改群名、全员禁言、变更群管理员和踢人。

这些操作首次调用时只创建待确认记录。交互示意如下，编号以机器人实际返回为准：

```text
你：把本群名称改为“周末读书会”。
机器人：该操作需要确认，请发送 /qq confirm a1b2c3d4
你：/qq confirm a1b2c3d4
机器人：返回执行结果。
```

确认命令必须由原调用者在原平台、原会话中真实发送。编号有有效期、只能使用一次，模型不能代替用户确认。

| 命令 | 用途 |
| --- | --- |
| `/qq pending` | 查看本人在当前会话中的有效待确认操作 |
| `/qq confirm <id>` | 确认并执行指定操作 |
| `/qq cancel <id>` | 取消指定待确认操作 |
| `/qq audit 20` | 查看最近 20 条审计，仅 AstrBot 管理员可用，条数范围为 1～100 |

可直接在 `confirmation.operations` 中增删 `tool.operation`。该列表是确认规则的唯一来源，跨会话本身不会额外触发确认。

<a id="faq"></a>

## 💡 常见问题

**模型为什么没有调用某个工具？**

先确认当前模型支持并启用了工具调用，当前会话使用 `aiocqhttp`。再检查能力包、禁用操作和调用者权限。`compact`、`balanced` 会按请求内容选择工具，可以把请求说得更明确，或切换到 `full` 排查。诊断页可查看能力是否启用。

**我是管理员，为什么仍提示权限不足？**

QQ 群管理员与 AstrBot 管理员是两种身份。账号和好友关系等全局操作要求 AstrBot 管理员；群管理还要检查机器人自身的群角色。操作其他群或好友时，也要检查跨会话开关与目标是否有效。

**为什么没有语音转写、戳一戳或红包回复？**

语音回退仅在 AstrBot 尚未产生转写时调用 NapCat，识别失败会保留原语音。戳一戳只响应其他用户对机器人自身的互动。红包可从 JSON/XML 卡片识别；NapCat 的 `walletElement` 识别需要网络适配器开启 `debug`，使事件包含 `raw`。同时检查对应的 `inbound` 开关。

**撤回后为什么没有标记，或者机器人没有回复？**

插件仅在已有上下文中追加标记，不因撤回事件唤醒模型。消息映射保留 180 秒，超出窗口或无法匹配已有上下文时，可能无法标记。

**为什么音乐卡片没有发出来？**

音乐卡片需要单独发送。按歌名搜索只接受歌名及可选歌手完全匹配的结果；按平台歌曲 ID 发送时，ID 必须来自用户当前消息，并依赖 NapCat 的 `musicSignUrl` 服务。NapCat 接受发送请求后，仍需以 QQ 接收端的实际展示为准。

**为什么本地文件或下载链接被拒绝？**

本地路径需位于 AstrBot 临时目录、插件专属数据目录，或 `files.allowed_roots` 配置的目录内。额外目录必须是已经存在的绝对目录，路径应对应 AstrBot 运行环境；容器部署时要检查挂载。下载还受文件大小、域名策略和网络配置约束，详见下方文件与网络说明。

**申请通知收不到，或收到后无法审批？**

检查通知开关、接收 QQ 号和私聊可达性；处理好友申请依赖插件已捕获并保存的申请事件。审批账号需有 AstrBot 管理权限，并继续满足目标群角色及跨会话规则。回复时可明确指出通知中的申请编号。

<a id="reference"></a>

## 📚 详细参考

<details>
<summary>全部 29 个模型工具</summary>

| 工具 | 主要能力 |
| --- | --- |
| `read_url` | 读取公开网页正文并建立隔离快照 |
| `read_page_section` | 按行继续阅读已缓存网页 |
| `find_in_page` | 在网页快照内查找字面量关键词 |
| `qq_status` | 登录、运行、版本、客户端、插件能力目录 |
| `qq_account_manage` | 修改账号资料、头像、在线状态 |
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
| `qq_send_message` | 发送结构化消息 |
| `qq_send_forward` | 群聊和私聊合并转发 |
| `qq_message_get` | 获取单条消息 |
| `qq_forward_get` | 读取并按深度展开合并转发 |
| `qq_message_manage` | 撤回、已读、消息表情回应 |
| `qq_recent_contacts` | 最近联系人 |
| `qq_media` | 按 ImageRef 重载会话原图、图片与语音文件、语音格式转换、OCR |
| `qq_group_files` | 群文件查询、上传、目录与文件管理 |
| `qq_private_files` | 私聊文件链接与上传 |
| `qq_essence` | 群精华消息 |
| `qq_notice` | 群公告 |

当前未实现主动添加好友、删除单向好友、匿名成员禁言、窗口抖动及账号 Cookies/Token/CSRF 等凭证读取。更多动作与支持范围见 [能力矩阵](./Capabilities.md)。

</details>

<details>
<summary>结构化消息与音乐卡片</summary>

以下是 `qq_send_message` 的工具参数示例，适合调试工具调用；日常对话可直接用自然语言提出请求。

```json
{
  "operation": "send",
  "params": {
    "target": {"type": "current"},
    "components": [
      {"type": "text", "text": "收到"},
      {"type": "face", "id": "14"}
    ]
  }
}
```

支持的组件类型包括 `text`、`at`、`reply`、`image`、`record`、`video`、`file`、`face`、`dice`、`rps`、`share`、`music`、`contact`、`location` 和 `json`。

- 媒体来源必须且只能填写 `path`、`url`、`base64`、`media_ref` 中的一项；Base64 支持 `data:*/*;base64,...`。
- `share` 必须单独发送，插件会校验 URL 并生成新闻 Ark JSON 卡片。NapCat 4.18.19 不接受原生 `share` 消息段。
- `music` 必须单独发送，避免 NapCat 丢弃音乐段。
- `dice`、`rps` 发送后会自动回查点数或手势，写入 `data.random_results`。回查失败会返回 `warnings`，已发送的消息仍记为发送成功。

分享组件示例：

```json
{"type": "share", "url": "https://example.com", "title": "标题", "content": "内容简介"}
```

| 音乐来源 | 组件示例 | 要求 |
| --- | --- | --- |
| QQ 音乐搜索 | `{"type":"music","music_type":"qq_search","query":"歌名","artist":"歌手"}` | 歌名及可选歌手必须完全匹配；搜索词会发送至 QQ 音乐公开接口 |
| 平台歌曲 ID | `{"type":"music","music_type":"qq","id":"歌曲ID"}` | ID 来自用户当前消息；支持 `qq`、`163`、`kugou`、`kuwo`、`migu`，依赖 `musicSignUrl` |
| 自定义卡片 | `{"type":"music","music_type":"custom","url":"https://example.com/song","image":"https://example.com/cover.jpg","title":"歌名"}` | `url`、`image` 必填；可补充 `audio`、`title`、`content` |

示例中的地址、歌名与 ID 请替换为真实值。插件不会接受模型猜测的歌曲 ID，也不会自行替换用户提供的链接。

</details>

<details>
<summary>消息语义化与组件防伪</summary>

语音优先使用 AstrBot 已有的转写。开启 `inbound.enhance_voice_messages` 后，尚未转写的语音会调用 NapCat 补充识别，最多尝试三次，重试间隔一秒；引用中的单条语音使用相同流程。识别失败、超时或为空时保留原始语音。NapCat 识别成功会在 INFO 日志中记录转写文本。

标准表情优先使用 NapCat 上报的名称，缺失时使用内置的 NapCat 4.18.19 表情名称表，未知 ID 会明确标记。卡片仅提取标题、提示、摘要等受限内容及去除查询参数的链接；联系人卡片通过校验后才提供群号或 QQ 号。

防伪用于区分真实组件与普通文字伪装，例如用户手打的骰子结果。`component_spoof_protection.enabled=true` 时：

| `verify_components` | 行为 |
| --- | --- |
| `false` | 按配置的类型范围匹配并标记伪装文字 |
| `true` | 额外加入组件格式系统提示词，并根据原始 OneBot 结构生成当前消息的可信类型清单 |

可信清单例如 `<qq_verified_components types="dice,rps"/>`，只用于当前用户消息，不写入历史，也不能用于验证更早的消息。历史中的伪装文字会保留“用户输入的文字”标记。

`protected_types` 控制两档共用的类型范围，防伪开启时不能为空。初始为 `red_packet`、`voice`、`dice`、`rps`、`poke`；还可选表情、媒体、联系人、位置、各类卡片、合并转发及扩展文件类型，完整枚举见配置 Schema。

</details>

<details>
<summary>文件、网络与审计</summary>

本地文件仅允许来自 AstrBot 临时目录、插件专属数据目录，以及 `files.allowed_roots` 中已经存在的绝对目录。路径会在解析符号链接后再次检查，目录、设备文件和越界路径会被拒绝。

本地文件与 HTTP(S) 下载初始上限为 100 MiB，Base64 解码和单次会话图片重载的初始上限为 10 MiB。插件创建的临时媒体初始保留 6 小时，NapCat 或 AstrBot 创建的文件不由本插件删除。模型获得的是媒体引用 `media_ref` 或会话图片 `image_ref`，不会获得 NapCat 返回的绝对媒体路径。

插件实际请求的 URL 会校验 HTTP(S) 协议、凭据、域名策略、DNS 结果和重定向。`network.allow_private_network=false` 时拒绝回环、私网、链路本地及保留地址。仅嵌入卡片而不由插件请求的 URL 不解析 DNS，但仍校验协议、凭据、域名、本地主机名及 IP 字面量。

`qq_media.get_record` 和 `qq_media.convert_record` 的 `file` 参数需要使用 OneBot/NapCat 提供的原始媒体标识，不能填写 AstrBot 本地临时路径。

插件保存规范化的 OneBot `request`、`notice` 事件，申请事件会去重。申请通知展示申请编号，不暴露底层 request flag；审批时由插件在内部定位记录，随后执行权限校验。

审计只保存操作名、调用者、目标、权限决策、结果码、耗时和参数哈希等元数据，不保存消息正文、完整 Base64、账号凭证、文件内容或完整本地路径。有副作用的操作会先写审计，审计不可用时不会执行。

</details>

<a id="development"></a>

## 🛠️ 开发验证

准备可导入 AstrBot 的开发环境，先安装 requirements.txt 中的插件依赖，以及 Ruff、pytest、pytest-asyncio 后，在插件根目录运行：

```sh
ruff format --check .
ruff check .
pytest -q
```

测试覆盖能力目录与契约、配置校验、权限与跨会话限制、确认绑定与单次使用、文件和消息处理、工具选择、入站组件、申请通知、撤回上下文和诊断页面。防抖测试包含独立用户历史、多媒体与特殊输入、预处理顺序、重复文本撤回、历史写入失败、任务取消及 AstrBot 真实 Agent 运行器的取消传播。

网页测试覆盖正文提取、中文编码、不可变快照、分页完整性、字面量查找、缓存隔离与过期、并发与取消、重定向校验、连接时 DNS 检查、压缩响应超限、部分响应及文件下载回归。HTTP 测试只使用本机临时服务器，不依赖外部站点。

NapCat 接口契约基线为 4.18.19。单元测试覆盖插件逻辑，QQ 实际行为还受账号权限、NapCat 版本及服务端能力影响。涉及删除、踢人或退群的实机验证，请使用专门的测试账号与测试群。

## 📌 已知问题记录

> 本节记录外部模型的兼容性问题，不代表本插件存在缺陷。

* Gemini 无法读取工具调用后追加的图片，可能因此重复调用图片、OCR 或 Python 工具；GPT 和 Grok 在相同流程下可以正常识别。
* Gemini 可能将推理式前导文本作为普通正文返回，导致内部分析出现在最终回复中。
