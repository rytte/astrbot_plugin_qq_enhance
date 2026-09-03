# QQ 扩展工具集

`astrbot_plugin_qq_extension_tools` 是面向 AstrBot 与 NapCat OneBot v11 的 QQ 模型工具插件。它将约 75 个明确支持的 QQ 操作合并为 26 个资源型工具，并在每次模型请求前按平台、会话、调用者权限和请求内容动态裁剪。

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

明确不实现以下能力：主动添加好友、删除单向好友、匿名成员禁言、窗口抖动、分享卡片，以及 Cookies/Token/CSRF 等账号凭证读取。NapCat 4.18.19 会以“未知的消息类型”拒绝 `shake` 和 `share` 消息段；好友戳一戳由 `qq_friend_interact.poke` 单独提供。

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

调用 `qq_send_message`：

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

支持的组件类型为：`text`、`image`、`record`、`video`、`file`、`at`、`reply`、`face`、`dice`、`rps`、`music`、`contact`、`location`、`json`。

用户按歌名点歌时使用 `{"type":"music","music_type":"qq_search","query":"准确歌名","artist":"可选歌手"}`，插件会查询 QQ 音乐，并且只发送歌名及可选歌手完全匹配的结果。不得凭记忆猜测歌曲 ID。平台 ID 卡片 `{"type":"music","music_type":"qq","id":"歌曲ID"}` 仅用于 ID 明确出现在用户当前消息中的场景；模型自行补出的 ID 会被拒绝。平台可为 `qq`、`163`、`kugou`、`kuwo` 或 `migu`；该格式依赖 NapCat 的 `musicSignUrl` 服务支持 ID 解析。也可直接使用 `{"type":"music","music_type":"custom","url":"跳转地址","image":"封面地址","audio":"可选音频地址","title":"可选标题","content":"可选简介"}`。音乐卡片必须作为唯一组件单独发送，否则插件会拒绝请求，防止 NapCat 静默丢弃失败的音乐段后仍返回其他组件的消息 ID。

媒体来源必须且只能选择 `path`、`url`、`base64`、`media_ref` 中的一项。Base64 也可使用标准 `data:*/*;base64,...` 形式。

## 文件与网络边界

- 默认本地根目录仅包括 AstrBot 临时目录和本插件专属数据目录。
- 额外目录通过 `files.allowed_roots` 配置，并且必须是已经存在的绝对目录。
- 路径会在解析符号链接后再次校验；目录、设备文件和越界路径会拒绝。
- 本地文件与 HTTP(S) 下载默认上限为 100 MiB，Base64 解码默认上限为 10 MiB。
- URL 会校验协议、凭据、域名策略、所有 DNS 结果以及每次重定向；默认拒绝回环、私网、链路本地和保留地址。
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
- `audit`：审计保留期。

配置只有当前 `_conf_schema.json` 中的一套字段。类型错误、未知枚举、未知 operation、无意义的逐操作规则会阻止插件加载；不存在旧字段别名或静默迁移。

## 事件与审计

插件记录规范化后的 OneBot `request` 和 `notice` 事件，但不会用事件主动触发 LLM。好友和群申请处理使用已捕获的 request flag。

审计默认保留 90 天，只保存 operation、调用者、目标、权限决策、结果码、耗时和参数哈希。不会保存消息正文、完整 Base64、账号凭证、文件内容或完整本地路径。有副作用操作会在协议调用前先写审计；审计不可用时不会执行该操作。

## 开发验证

```powershell
ruff format .
ruff check .
pytest -q
```

单元测试覆盖能力目录、契约版本、严格配置、权限矩阵、跨会话限制、确认绑定与单次使用、文件/Base64、安全消息转换和请求局部工具裁剪。真实 QQ 上的破坏性集成测试不应在生产账号或生产群执行。
