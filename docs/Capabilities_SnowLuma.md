# SnowLuma v1.14.22 与 NapCat 动作覆盖核对

核对日期：2026-10-15。

本文件复制 [Capabilities_NapCat.md](./Capabilities_NapCat.md) 中“NapCat 全部动作与插件覆盖”表格的全部 177 行，保留原有五列、行序和插件支持标记，在右侧增加“SnowLuma v1.14.22 支持情况”和“核对记录／差异”两列。原五列保留核对时的仓库快照；当前插件适配范围见下文“当前适配状态”和 README，表内原插件支持标记不代表 SnowLuma 的支持承诺。

核对基线为 [SnowLuma v1.14.22 正式版](https://github.com/SnowLuma/SnowLuma/releases/tag/v1.14.22)，固定提交 [87527cb7641a5a42f8f0efb73cb066102e004dee](https://github.com/SnowLuma/SnowLuma/commit/87527cb7641a5a42f8f0efb73cb066102e004dee)。插件源码基线为 `e6ec4653a4ef3ff952e6ff666d0cdc853876a803`。

核对方式：静态检查动作注册表、名称与别名、参数声明、处理器分支，以及相关消息/媒体处理代码。“本文没有启动 SnowLuma、登录 QQ 或执行在线动作，因此“有实现”表示存在实际处理逻辑，不表示 QQ 实测通过，也不表示全部参数和行为与 NapCat 一致。未注册项按精确动作名称判断，相近功能不计为原名称可用。

## 核对结果统计

| 项目 | 数量 |
|---|---:|
| 从原表复制的 NapCat 动作 | 177 |
| SnowLuma 注册了相同名称的动作（含别名、占位及拒绝项） | 163 |
| 其中有实际处理逻辑（含受限实现及别名） | 155 |
| 其中仅有占位返回 | 6 |
| 其中明确拒绝／未实现 | 2 |
| 未注册原名称 | 14 |
| 注册为其他动作别名的原名称（包含在上述注册数中） | 3 |

SnowLuma 列的状态口径：

- **✅️ 有实现／已注册别名**：已注册并有对应处理逻辑；备注记录调用形式与已发现的约束。
- **⚠️ 参数／输入／返回等受限**：有处理逻辑，但存在输入范围、字段、缓存、参数名称或行为差异；不能直接承诺插件对应入口完整可用。
- **⚠️ 占位**：只返回固定值或无操作成功，不计为具备实际功能。
- **❌️ 已注册但拒绝**：路由存在，但处理器直接返回不支持或未实现。
- **❌️ 未注册**：统一动作注册表没有此精确名称。

## NapCat 全部动作与插件覆盖

| 分类 | NapCat 动作 | NapCat 能力 | 插件支持 | 插件入口 | SnowLuma v1.14.22 支持情况 | 核对记录／差异 |
|---|---|---|---|---|---|---|
| 核心接口 | `friend_poke` | 私聊戳一戳 | ✅️ | `qq_friend_interact.poke` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L434) | 好友拍一拍。主要参数：user_id、target_id。 |
| 核心接口 | `group_poke` | 群聊戳一戳 | ✅️ | `qq_group_member_manage.poke` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L447) | 群拍一拍。主要参数：group_id、user_id。 |
| 核心接口 | `send_poke` | 发送戳一戳 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L456) | 拍一拍（群聊/私聊自动路由）。主要参数：user_id、group_id。 |
| 系统接口 | `can_send_image` | 是否可以发送图片 | ❌️ | — | [⚠️ 固定能力声明](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/info.ts#L71) | 返回 `{yes}`；该版本运行上下文固定声明图片发送能力为 true，不进行实时发送探测。 |
| 系统接口 | `can_send_record` | 是否可以发送语音 | ❌️ | — | [⚠️ 固定能力声明](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/info.ts#L86) | 返回 `{yes}`；该版本运行上下文固定声明语音发送能力为 true，不进行实时发送探测。 |
| 系统接口 | `clean_cache` | 清理缓存 | ❌️ | — | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L952) | 直接返回成功，没有执行缓存清理；不能按实际清理能力使用。 |
| 系统接口 | `get_credentials` | 获取登录凭证 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L921) | 获取凭证。主要参数：domain。返回说明：{ cookies, token, csrf_token }：Cookie 字符串与 CSRF 令牌（token 与 csrf_token 同值）。 |
| 系统接口 | `get_csrf_token` | 获取 CSRF Token | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L902) | 获取 CSRF 令牌。返回说明：{ token }：CSRF 令牌（bkn，数值）。 |
| 系统接口 | `get_doubt_friends_add_request` | 获取可疑好友申请 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1883) | 获取可疑好友申请。主要参数：count。返回说明：可疑好友申请数组，每项含 uid（作为处理用 flag）、昵称、来源、留言与申请时间。 |
| 系统接口 | `get_group_system_msg` | 获取群系统消息 | ✅️ | `qq_group_request.list` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L223) | 返回扁平申请数组，支持 `group_id`、`only_pending`、`count`；区别于 NapCat 的分类对象。插件现有按群过滤也接受数组。 |
| 系统接口 | `get_login_info` | 获取登录号信息 | ✅️ | `qq_status.login` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/info.ts#L9) | 已注册同名动作并有实际处理逻辑。返回说明：当前登录账号的 QQ 号与昵称。 |
| 系统接口 | `get_status` | 获取运行状态 | ✅️ | `qq_status.runtime` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/info.ts#L28) | 已注册同名动作并有实际处理逻辑。返回说明：运行状态。`online` 表示账号在线；`good` 表示已确认的收发链路健康状态；`time` 为当前账号服务实例运行秒数，与 #sl 同源。 |
| 系统接口 | `get_version_info` | 获取版本信息 | ✅️ | `qq_status.version` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/info.ts#L48) | 返回 `app_name=SnowLuma`、`app_version=1.14.22-node`、`protocol_version=v11`；插件当前的 NapCat 校验仍会拒绝接入。 |
| 系统接口 | `nc_get_packet_status` | 获取Packet状态 | ❌️ | — | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2183) | 固定返回成功与 `data=null`，没有 packet 状态信息。 |
| 系统接口 | `set_doubt_friends_add_request` | 处理可疑好友申请 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1913) | 处理可疑好友申请。主要参数：flag、approve。 |
| 系统接口 | `set_restart` | 重启服务 | ❌️ | — | [❌️ 已注册但拒绝](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L943) | 名称已注册，但固定返回 ACTION_FAILED / not supported；没有重启实现。 |
| 系统扩展 | `add_custom_face` | 添加自定义表情 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L560) | 添加收藏表情。主要参数：file。 |
| 系统扩展 | `bot_exit` | 退出登录 | ❌️ | — | [⚠️ 语义不同](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2173) | 延迟调用 `process.exit(0)`，退出整个 SnowLuma 进程；不是单独注销某个 QQ 账号。 |
| 系统扩展 | `delete_custom_face` | 删除自定义表情 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L549) | 删除收藏表情。主要参数：emoji_id。 |
| 系统扩展 | `fetch_custom_face` | 获取自定义表情 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1321) | 获取自定义表情。主要参数：count、return_type。返回说明：字符串数组：return_type=url 时为图片 URL，return_type=id 时为 emoji_id。 |
| 系统扩展 | `fetch_custom_face_detail` | 获取自定义表情详情 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1344) | 获取自定义表情详情。主要参数：count。返回说明：自定义表情详情数组，包含资源标识、图片地址、摘要与描述。 |
| 系统扩展 | `get_collection_list` | 获取收藏列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1947) | 获取收藏列表。主要参数：category、count。返回说明：返回收藏条目、是否还有更多数据及底部时间游标。 |
| 系统扩展 | `get_mini_app_ark` | 获取小程序 Ark | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2643) | 获取小程序卡片 ark。主要参数：type、title、desc、picUrl、pic_url、jumpUrl、jump_url。 |
| 系统扩展 | `get_rkey` | 获取扩展 RKey | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2337) | 获取下载 rkey。 |
| 系统扩展 | `get_rkey_server` | 获取 RKey 服务器 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2350) | 从下载 RKey 列表组装 expired_time、name=SnowLuma 及可用的私聊/群聊 RKey；没有可用 RKey 时明确失败。 |
| 系统扩展 | `get_robot_uin_range` | 获取机器人 UIN 范围 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现可直接替代的同义 action。 |
| 系统扩展 | `nc_get_rkey` | 获取 RKey | ❌️ | — | [✅️ 已注册别名](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2337) | 已注册为 `get_rkey` 的别名，使用同一下载 RKey 查询处理器。 |
| 系统扩展 | `nc_get_user_status` | 获取用户在线状态 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2209) | 获取用户在线/扩展状态。主要参数：user_id。返回说明：{ status, ext_status }：用户在线状态码与扩展状态码。 |
| 系统扩展 | `send_packet` | 发送原始数据包 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2697) | 接收 cmd、十六进制 data、rsp；发送原始 SSO 包，返回响应十六进制或 null。 |
| 系统扩展 | `set_custom_face_desc` | 修改自定义表情描述 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 此名称未注册；相近能力是 `modify_custom_face(emoji_id, desc)`，参数不同，不会自动转调。 |
| 系统扩展 | `set_input_status` | 设置输入状态 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2077) | 设置输入状态。主要参数：user_id、event_type。 |
| 系统扩展 | `set_online_status` | 设置在线状态 | ✅️ | `qq_account_manage.set_online_status` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1075) | 设置在线状态。主要参数：status、ext_status、battery_status。 |
| 用户接口 | `get_cookies` | 获取 Cookies | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L883) | 获取 Cookies。主要参数：domain。返回说明：{ cookies }：指定域名的 Cookie 字符串。 |
| 用户接口 | `get_friend_list` | 获取好友列表 | ✅️ | `qq_friend_list.friends` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/friend.ts#L6) | 有好友列表实现；处理器不声明 `no_cache`，插件暴露的该参数不会生效。 |
| 用户接口 | `get_recent_contact` | 获取最近会话 | ✅️ | `qq_recent_contacts.list` | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1571) | 接受 count 但固定返回空数组；不能据此判断账号没有最近会话。 |
| 用户接口 | `send_like` | 点赞 | ✅️ | `qq_friend_interact.like` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L420) | 点赞。主要参数：user_id、times。 |
| 用户接口 | `set_friend_add_request` | 处理加好友请求 | ✅️ | `qq_friend_request.approve`<br>`qq_friend_request.reject` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/request.ts#L6) | 同意/拒绝已实现；只声明 `flag`、`approve`，插件 approve 操作可传的 `remark` 不会生效。 |
| 用户接口 | `set_friend_remark` | 设置好友备注 | ✅️ | `qq_friend_manage.set_remark` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L962) | 设置好友备注。主要参数：user_id、remark。 |
| 用户扩展 | `get_friends_with_category` | 获取带分组的好友列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1499) | 获取分组好友列表。返回说明：好友分组数组；每组包含 categoryId、categoryName、categoryMbCount 和 buddyList。 |
| 用户扩展 | `get_profile_like` | 获取资料点赞 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1267) | 获取资料点赞。主要参数：user_id、start、count。返回说明：点赞资料：uid、最近点赞时间、收藏与点赞统计及用户明细。 |
| 用户扩展 | `get_unidirectional_friend_list` | 获取单向好友列表 | ✅️ | `qq_friend_list.unidirectional` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1707) | 获取单向好友列表。 |
| 用户扩展 | `set_diy_online_status` | 设置自定义在线状态 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1093) | 设置自定义在线状态。主要参数：face_id、face_type、wording。 |
| 群组接口 | `_del_group_notice` | 删除群公告 | ✅️ | `qq_notice.delete` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2457) | 删除群公告（fid 或 notice_id 二选一）。主要参数：group_id、fid、notice_id。 |
| 群组接口 | `_get_group_notice` | 获取群公告 | ✅️ | `qq_notice.detail`<br>`qq_notice.list` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L759) | 返回普通公告与新成员公告的合并数组，后者由 send_to_new_members 标识。 |
| 群组接口 | `delete_essence_msg` | 移出精华消息 | ✅️ | `qq_essence.remove` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L484) | 移除精华消息。主要参数：message_id。 |
| 群组接口 | `get_essence_msg_list` | 获取群精华消息 | ✅️ | `qq_essence.list` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L494) | 获取精华消息列表。主要参数：group_id。 |
| 群组接口 | `get_group_detail_info` | 获取群详细信息 | ❌️ | — | [⚠️ 字段受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2108) | 同名入口存在，但复用普通 `getGroupInfo` 和相同返回 schema；不能视为完整复刻 NapCat 的详细群字段。 |
| 群组接口 | `get_group_ignore_add_request` | 获取群被忽略的加群请求 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1155) | 获取被忽略的入群请求（NapCat）。返回说明：被忽略的入群请求数组（NapCat 字段命名），每项含请求序列、邀请人、群信息与处理标记。 |
| 群组接口 | `get_group_ignored_notifies` | 获取群忽略通知 | ✅️ | `qq_group_request.ignored` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1108) | 返回被过滤的入群请求数组，含群号、申请人、邀请人、flag 等；插件现有按群过滤可处理数组。 |
| 群组接口 | `get_group_info` | 获取群信息 | ✅️ | `qq_group_info.detail` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L64) | 获取群信息。主要参数：group_id、no_cache。返回说明：群信息对象。 |
| 群组接口 | `get_group_list` | 获取群列表 | ✅️ | `qq_group_list.list` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L27) | 支持 no_cache，返回群列表；批量列表中的 `group_level` 固定为 0，详细资料需另查。 |
| 群组接口 | `get_group_member_info` | 获取群成员信息 | ✅️ | `qq_group_members.detail`<br>`qq_user_info.group_member` | [⚠️ 部分字段占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L141) | 支持 no_cache，返回 role 等成员资料；area、unfriendly、title_expire_time、card_changeable 使用源码注明的占位值。 |
| 群组接口 | `get_group_member_list` | 获取群成员列表 | ✅️ | `qq_group_members.list` | [⚠️ 部分字段占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L94) | 支持 no_cache，返回成员列表；部分 QQ NT 不提供的字段使用固定值，不能视为真实成员属性。 |
| 群组接口 | `get_group_shut_list` | 获取群禁言列表 | ✅️ | `qq_group_info.mute_list` | [⚠️ 缓存派生](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1201) | 从成员列表缓存派生仍在禁言中的成员，返回 user_id、nickname、shut_up_time；源码注明可能约有 60 秒延迟。 |
| 群组接口 | `send_group_msg` | 发送群消息 | ⚠️ 受限封装 | `qq_send_message.send` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/message.ts#L130) | 支持 group_id、message、auto_escape，返回 message_id；组件范围仍取决于消息解析与发送逻辑。 |
| 群组接口 | `set_essence_msg` | 设置精华消息 | ✅️ | `qq_essence.add` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L474) | 设置精华消息。主要参数：message_id。 |
| 群组接口 | `set_group_add_request` | 处理加群请求 | ✅️ | `qq_group_request.approve`<br>`qq_group_request.reject` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/request.ts#L19) | 接收原始事件/列表的 opaque flag 及同意/拒绝参数；不可构造或跨实现复用 flag。 |
| 群组接口 | `set_group_admin` | 设置群管理员 | ✅️ | `qq_group_member_manage.admin` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L224) | 设置/取消管理员。主要参数：group_id、user_id、enable。 |
| 群组接口 | `set_group_ban` | 群组禁言 | ✅️ | `qq_group_member_manage.ban` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L26) | 禁言群成员（duration=0 解除）。主要参数：group_id、user_id、duration。 |
| 群组接口 | `set_group_card` | 设置群名片 | ✅️ | `qq_group_member_manage.card` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L234) | 设置群名片（空字符串清除）。主要参数：group_id、user_id、card。 |
| 群组接口 | `set_group_kick` | 群组踢人 | ✅️ | `qq_group_member_manage.kick` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L6) | 踢出群成员。主要参数：group_id、user_id、reject_add_request。 |
| 群组接口 | `set_group_leave` | 退出群组 | ✅️ | `qq_group_manage.leave` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L254) | 已实现退群；不声明插件可传的 `is_dismiss`，不会按该参数选择解散群。 |
| 群组接口 | `set_group_member_invite_policy` | 设置群成员邀请策略 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L75) | 设置群成员邀请策略。主要参数：group_id、policy。 |
| 群组接口 | `set_group_member_permissions` | 设置群成员功能权限 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L102) | 设置群成员权限（仅群主可改）。主要参数：group_id、allow_member_upload_album、allow_member_temporary_session、allow_member_create_group。 |
| 群组接口 | `set_group_name` | 设置群名称 | ✅️ | `qq_group_manage.name` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L244) | 设置群名。主要参数：group_id、group_name。 |
| 群组接口 | `set_group_new_member_history_visibility` | 设置新成员历史消息可见性 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L92) | 设置新成员是否可查看历史消息。主要参数：group_id、visible。 |
| 群组接口 | `set_group_whole_ban` | 全员禁言 | ✅️ | `qq_group_manage.whole_ban` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L36) | 全员禁言开关。主要参数：group_id、enable。 |
| 群组扩展 | `cancel_group_album_media_like` | 取消点赞群相册媒体 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L234) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、album_id、batch_id、lloc。 |
| 群组扩展 | `cancel_group_todo` | 取消群待办 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2774) | 接收 group_id、message_id，校验所属群及权威 QQ 序列后调用取消群待办。 |
| 群组扩展 | `complete_group_todo` | 完成群待办 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2767) | 接收 group_id、message_id，校验所属群及权威 QQ 序列后调用完成群待办。 |
| 群组扩展 | `del_group_album_media` | 删除群相册媒体 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L247) | 接收 group_id、album_id、lloc；调用群相册图片/视频删除，该版本也覆盖视频 ID。 |
| 群组扩展 | `do_group_album_comment` | 发表群相册评论 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L207) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、album_id、lloc、content。 |
| 群组扩展 | `get_group_album_media_list` | 获取群相册媒体列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L181) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、album_id、attach_info。返回说明：相册图片/视频列表及下一页分页游标；视频项包含 id、url、cover、尺寸、时长和多规格地址。 |
| 群组扩展 | `get_group_info_ex` | 获取群详细信息 (扩展) | ✅️ | `qq_group_info.detail_ex` | [⚠️ 字段受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2091) | 同名入口存在，但复用普通 `getGroupInfo` 和相同返回 schema；不会提供 NapCat 特有的完整扩展群对象。 |
| 群组扩展 | `get_group_signed_list` | 获取群组今日打卡列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1231) | 获取群今日打卡列表。主要参数：group_id。 |
| 群组扩展 | `get_qun_album_list` | 获取群相册列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L89) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、attach_info。返回说明：NapCat 风格的相册列表封套：{album_list, attach_info, has_more}。 |
| 群组扩展 | `send_group_sign` | 群打卡 | ❌️ | — | [✅️ 已注册别名](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2688) | 已注册为 `set_group_sign` 的别名，使用同一群签到处理器。 |
| 群组扩展 | `set_group_add_option` | 设置群加群选项 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L46) | 设置加群选项。主要参数：group_id、add_type、group_question、group_answer。 |
| 群组扩展 | `set_group_album_media_like` | 点赞群相册媒体 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L220) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、album_id、batch_id、lloc。 |
| 群组扩展 | `set_group_remark` | 设置群备注 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L975) | 设置群备注。主要参数：group_id、remark。 |
| 群组扩展 | `set_group_robot_add_option` | 设置群机器人加群选项 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1932) | 接收 group_id、可选 robot_member_switch、robot_member_examine，调用群机器人加群选项设置；未提供的字段保持原值。 |
| 群组扩展 | `set_group_search` | 设置群搜索选项 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L62) | 设置群被搜索方式（群指纹 / 群号搜索开关）。主要参数：group_id、no_finger_open、no_code_finger_open。 |
| 群组扩展 | `set_group_sign` | 群打卡 | ✅️ | `qq_group_manage.sign` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2688) | 群签到。主要参数：group_id。 |
| 群组扩展 | `set_group_todo` | 设置群待办 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2760) | 接收 group_id、message_id，校验所属群及权威 QQ 序列后调用设置群待办。 |
| 群组扩展 | `upload_image_to_qun_album` | 上传图片到群相册 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-album.ts#L146) | 已注册同名动作并有实际处理逻辑。主要参数：group_id、album_id、album_name、file。 |
| 消息接口 | `_mark_all_as_read` | 标记所有消息已读 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1002) | 使用 `listReadSessions()` 中的群聊/私聊会话标记已读，作用范围由 SnowLuma 已知会话决定。 |
| 消息接口 | `delete_msg` | 撤回消息 | ✅️ | `qq_message_manage.recall` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/message.ts#L162) | 接收 message_id，依赖可撤回消息元数据，找不到消息或无法撤回时失败。 |
| 消息接口 | `forward_friend_single_msg` | 转发单条消息到好友 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1241) | 转发单条消息给好友。主要参数：message_id、user_id。 |
| 消息接口 | `forward_group_single_msg` | 转发单条消息到群 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1254) | 转发单条消息到群。主要参数：message_id、group_id。 |
| 消息接口 | `get_msg` | 获取消息 | ✅️ | `qq_message_get.get` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/message.ts#L141) | 从消息存储查询，未命中时失败；补 real_id 并刷新图片 URL，不提供任意消息的无缓存远端查询。 |
| 消息接口 | `mark_group_msg_as_read` | 标记群聊已读 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L654) | 必须提供可查到元数据的 message_id，可选 group_id 用于核对所属群；不是仅传 group_id 即可调用。 |
| 消息接口 | `mark_msg_as_read` | 标记消息已读 (Go-CQHTTP) | ✅️ | `qq_message_manage.mark_read` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L698) | 标记消息已读（群聊/私聊自动路由）。主要参数：message_id、target_id。 |
| 消息接口 | `mark_private_msg_as_read` | 标记私聊已读 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L676) | 必须提供可查到元数据的 message_id，可选 user_id 用于核对所属私聊；不是仅传 user_id 即可调用。 |
| 消息接口 | `send_msg` | 发送消息 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/message.ts#L82) | 支持群聊/私聊自动路由及群临时会话；返回 message_id。 |
| 消息接口 | `send_private_msg` | 发送私聊消息 | ⚠️ 受限封装 | `qq_send_message.send` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/message.ts#L109) | 支持 user_id、message、auto_escape；可带来源 group_id 回复临时会话，返回 message_id。 |
| 消息扩展 | `ArkShareGroup` | 获取群推荐 Ark（旧别名，仅返回数据） | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 此大小写名称未注册；对应群推荐卡片入口是 `send_group_ark_share` / `share_group_ex`，不会自动转调。 |
| 消息扩展 | `ArkSharePeer` | 获取用户或群推荐 Ark（旧别名，仅返回数据） | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 此大小写名称未注册；对应联系人/群推荐卡片入口是 `send_ark_share` / `share_peer`，不会自动转调。 |
| 消息扩展 | `click_inline_keyboard_button` | 点击内联键盘按钮 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2667) | 点击内联键盘按钮。主要参数：group_id、bot_appid、msg_seq、button_id、callback_data。 |
| 消息扩展 | `fetch_emoji_like` | 获取表情点赞详情 | ❌️ | — | [⚠️ 字段受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1413) | 提供 NapCat 形状的分页结果；`nickName`、`headUrl` 固定为空，cookie 为本实现的偏移游标。 |
| 消息扩展 | `fetch_ptt_text` | 获取语音转文字结果 | ⚠️ 配置启用 | `voice_recognition.enhance_voice_messages` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L862) | 接收 message_id，返回 {text}；读取缓存的语音指纹，触发 QQ 转写并等待结果。插件现有调用参数一致。 |
| 消息扩展 | `get_emoji_likes` | 获取消息表情点赞列表 | ❌️ | — | [⚠️ 字段受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1378) | 返回 emoji_like_list，user_id 为字符串；`nick_name` 固定为空，不能提供实际昵称。 |
| 消息扩展 | `send_ark_share` | 获取用户或群推荐 Ark（标准名，仅返回数据） | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1777) | 返回 {arkMsg} 推荐联系人/群卡片数据；不直接发送消息，也不是任意 URL 分享接口。 |
| 消息扩展 | `send_group_ark_share` | 获取群推荐 Ark（标准名，仅返回数据） | ❌️ | — | [⚠️ 实现不同](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1869) | 返回群推荐 Ark JSON 字符串；源码说明使用群推荐联系人接口替代 NapCat 的另一内核接口，卡片可能不同。 |
| 消息扩展 | `set_msg_emoji_like` | 设置消息表情点赞 | ✅️ | `qq_message_manage.reaction_add`<br>`qq_message_manage.reaction_remove` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L988) | 设置消息表情回应。主要参数：message_id、emoji_id、set。 |
| 文件接口 | `get_file` | 获取文件 | ❌️ | — | [⚠️ 范围受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2149) | 只解析图片/语音缓存；无法通过此入口解析普通群文件/私聊文件，应使用对应文件 URL 接口。 |
| 文件接口 | `get_group_file_url` | 获取群文件URL | ✅️ | `qq_group_files.url` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L81) | 获取群文件下载链接。主要参数：group_id、file_id、busid。返回说明：群文件下载链接。 |
| 文件接口 | `get_image` | 获取图片 | ✅️ | `qq_media.get_image` | [⚠️ 返回不同](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L813) | 只解析图片缓存，返回 file/url、字符串型 file_size、file_name；file 通常是 URL，不是 NapCat 式本地下载路径。 |
| 文件接口 | `get_private_file_url` | 获取私聊文件URL | ✅️ | `qq_private_files.url` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L296) | 接收 file_id，可选 user_id、file_hash，返回 {url}；file_id 为原始 UUID，file_hash 来源于 SnowLuma 文件消息段。 |
| 文件接口 | `get_record` | 获取语音 | ✅️ | `qq_media.convert_record`<br>`qq_media.get_record` | [⚠️ 返回不同](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L830) | 只解析语音缓存；传 out_format 时附加转码后的 `base64` 和 out_format，file/url 仍保留原资源信息，不返回转码后的本地路径。 |
| 文件接口 | `ocr_image` | 图片 OCR 识别 | ✅️ | `qq_media.ocr` | [⚠️ 输入不匹配](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2396) | 仅接受 HTTP(S) 图片 URL 或可解析为 URL 的缓存图片 ID；明确拒绝本地文件/base64。插件当前会先把输入下载为本地路径，因此不能原样调用。 |
| 文件扩展 | `cancel_online_file` | 取消在线文件 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现在线文件取消接口。 |
| 文件扩展 | `create_flash_task` | 创建闪传任务 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2783) | 创建闪传任务。主要参数：files、name、thumb_path。 |
| 文件扩展 | `download_fileset` | 下载文件集 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2877) | 按 fileset_id 及可选 file_name/file_index 解析下载地址；返回 url、file_name、file_size，由调用方下载。 |
| 文件扩展 | `get_fileset_id` | 获取文件集 ID | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2921) | 从 QQ 闪传分享码或官方分享链接获取 fileset_id。主要参数：share_code。返回说明：{ fileset_id }：解析出的文件集 ID。 |
| 文件扩展 | `get_fileset_info` | 获取文件集信息 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2800) | 获取文件集信息。主要参数：fileset_id。 |
| 文件扩展 | `get_flash_file_list` | 获取闪传文件列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2810) | 获取闪传文件列表。主要参数：fileset_id。 |
| 文件扩展 | `get_flash_file_url` | 获取闪传文件链接 | ❌️ | — | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2830) | 返回 {url}；虽然声明 file_name，但处理器实际只将 fileset_id、file_index 传给下载地址查询。 |
| 文件扩展 | `get_online_file_msg` | 获取在线文件消息 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现在线文件消息查询接口。 |
| 文件扩展 | `get_share_link` | 获取文件分享链接 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2844) | 获取文件分享链接。主要参数：fileset_id。 |
| 文件扩展 | `move_group_file` | 移动群文件 | ✅️ | `qq_group_files.move` | [⚠️ 参数不匹配](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L222) | 必填 `parent_directory`、`target_directory`；插件当前传 `current_parent_directory`、`target_parent_directory`，直接调用会因缺参失败。 |
| 文件扩展 | `receive_online_file` | 接收在线文件 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现在线文件接收接口。 |
| 文件扩展 | `refuse_online_file` | 拒绝在线文件 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现在线文件拒收接口。 |
| 文件扩展 | `rename_group_file` | 重命名群文件 | ✅️ | `qq_group_files.rename` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L238) | 支持 file_id、current_parent_directory、new_name，返回 {ok:true}；插件参数名称与此一致。 |
| 文件扩展 | `send_flash_msg` | 发送闪传消息 | ❌️ | — | [⚠️ 返回受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2899) | 可发送到群或私聊，但成功固定返回 `message_id=0`，没有可用于撤回、设精华的真实消息 ID。 |
| 文件扩展 | `send_online_file` | 发送在线文件 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称；离线文件上传/发送不是该在线传输接口。 |
| 文件扩展 | `send_online_folder` | 发送在线文件夹 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，未发现在线文件夹发送接口。 |
| 文件扩展 | `trans_group_file` | 传输群文件 | ✅️ | `qq_group_files.transfer` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2125) | 转存群文件。主要参数：group_id、file_id。返回说明：{ ok: true }。 |
| AI 扩展 | `get_ai_record` | 获取 AI 语音 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2273) | 生成 AI 语音。主要参数：group_id、character、text、chat_type。 |
| AI 扩展 | `send_group_ai_record` | 发送群 AI 语音 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2288) | 发送 AI 语音到群。主要参数：group_id、character、text、chat_type。返回说明：{ message_id }：已发送 AI 语音的 OneBot 消息 ID。 |
| 频道接口 | `get_guild_list` | 获取频道列表 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，不能据此声明支持 QQ 频道列表。 |
| 频道接口 | `get_guild_service_profile` | 获取频道个人信息 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称，不能据此声明支持 QQ 频道个人资料。 |
| Go-CQHTTP | `.handle_quick_operation` | 处理快速操作 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L266) | 作为 raw action 保留并绑定处理器；接收 context、operation，调用 OneBot 快速操作执行逻辑。 |
| Go-CQHTTP | `_get_model_show` | 获取机型显示 | ❌️ | — | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1647) | 模拟结果：返回 variants 数组，model_show 回显 model（默认 snowluma），need_pay 固定 false；没有真实机型展示查询。 |
| Go-CQHTTP | `_send_group_notice` | 发送群公告 | ✅️ | `qq_notice.send` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L723) | 发送群公告（支持置顶、弹窗、新成员、群昵称引导与确认）。主要参数：group_id、content、image、pinned、type、send_to_new_members、is_show_edit_card、tip_window_type、confirm_required。 |
| Go-CQHTTP | `_set_model_show` | 设置机型 | ❌️ | — | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1678) | 直接返回成功，没有执行机型展示设置。 |
| Go-CQHTTP | `check_url_safely` | 检查URL安全性 | ❌️ | — | [⚠️ 占位](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1043) | 固定返回 `{level:1}`，没有执行 URL 安全检测。 |
| Go-CQHTTP | `create_group_file_folder` | 创建群文件目录 | ✅️ | `qq_group_files.mkdir` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L254) | 接收 name、parent_id，真实创建群文件夹；返回 NapCat 形状的 result、groupItem.folderInfo。 |
| Go-CQHTTP | `delete_friend` | 删除好友 | ✅️ | `qq_friend_manage.delete` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/friend.ts#L83) | 删除好友。主要参数：user_id、block。 |
| Go-CQHTTP | `delete_group_file` | 删除群文件 | ✅️ | `qq_group_files.delete` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L212) | 删除群文件。主要参数：group_id、file_id。 |
| Go-CQHTTP | `delete_group_folder` | 删除群文件目录 | ✅️ | `qq_group_files.rmdir` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2198) | 同名入口已实现，调用与 delete_group_file_folder 相同的文件夹删除逻辑。 |
| Go-CQHTTP | `download_file` | 下载文件 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2579) | 下载文件（url 或 base64）到 data/downloads。主要参数：url、base64、name、headers。返回说明：{ file }。 |
| Go-CQHTTP | `get_forward_msg` | 获取合并转发消息 | ✅️ | `qq_forward_get.get` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2540) | 接受字符串 id 或 message_id，返回 {messages}；可从缓存的转发消息中解析资源标识。 |
| Go-CQHTTP | `get_friend_msg_history` | 获取好友历史消息 | ✅️ | `qq_friend_history.list` | [⚠️ 锚点不匹配](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L628) | 返回 {messages}；锚点是 `message_id`，插件发送的 `message_seq` 不会被读取，非零锚点查询需要调整。 |
| Go-CQHTTP | `get_group_at_all_remain` | 获取群艾特全体剩余次数 | ✅️ | `qq_group_info.at_all_remain` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1687) | 获取群 @全体成员 剩余次数。主要参数：group_id。返回说明：{ can_at_all, remain_at_all_count_for_group, remain_at_all_count_for_uin }：@全体可用性与剩余次数。 |
| Go-CQHTTP | `get_group_file_system_info` | 获取群文件系统信息 | ✅️ | `qq_group_files.info` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1013) | 获取群文件系统信息。主要参数：group_id。返回说明：{ file_count, limit_count, used_space, total_space }：群文件数量与容量信息（均为服务端实际值）。 |
| Go-CQHTTP | `get_group_files_by_folder` | 获取群文件夹文件列表 | ✅️ | `qq_group_files.list_folder` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L154) | 获取群子目录文件列表。主要参数：group_id、folder_id、folder。返回说明：群文件系统信息（文件与文件夹列表）。 |
| Go-CQHTTP | `get_group_honor_info` | 获取群荣誉信息 | ✅️ | `qq_group_info.honor` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-info.ts#L200) | 获取群荣誉信息。主要参数：group_id、type。 |
| Go-CQHTTP | `get_group_msg_history` | 获取群历史消息 | ✅️ | `qq_group_history.list` | [⚠️ 锚点不匹配](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L600) | 返回 {messages}；锚点是 `message_id`，插件发送的 `message_seq` 不会被读取，非零锚点查询需要调整。 |
| Go-CQHTTP | `get_group_root_files` | 获取群根目录文件列表 | ✅️ | `qq_group_files.list_root` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L99) | 获取群根目录文件列表。主要参数：group_id。返回说明：群文件系统信息（文件与文件夹列表）。 |
| Go-CQHTTP | `get_online_clients` | 获取在线客户端 | ✅️ | `qq_status.clients` | [⚠️ 快照受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1585) | 返回本次会话已观测到的在线设备快照 {clients}；`no_cache=true` 明确失败，未观测到快照也失败。 |
| Go-CQHTTP | `get_stranger_info` | 获取陌生人信息 | ✅️ | `qq_user_info.stranger` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/friend.ts#L32) | 有用户资料查询；不声明 no_cache，缺少可靠来源的会员/注册字段省略，查不到资料时部分基础字段使用空值。 |
| Go-CQHTTP | `send_forward_msg` | 发送合并转发消息 | ❌️ | — | [⚠️ 无目标仅上传](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2469) | 按目标发送并返回 message_id、res_id、forward_id；无目标时仅上传转发内容，`message_id=0`。 |
| Go-CQHTTP | `send_group_forward_msg` | 发送群合并转发消息 | ⚠️ 受限封装 | `qq_send_forward.send` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2505) | 发送群合并转发。主要参数：group_id、messages、message。返回说明：{ message_id, res_id, forward_id }。 |
| Go-CQHTTP | `send_private_forward_msg` | 发送私聊合并转发消息 | ⚠️ 受限封装 | `qq_send_forward.send` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2522) | 发送私聊合并转发。主要参数：user_id、messages、message。返回说明：{ message_id, res_id, forward_id }。 |
| Go-CQHTTP | `set_group_portrait` | 设置群头像 | ✅️ | `qq_group_manage.avatar` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L277) | 设置群头像。主要参数：group_id、file。 |
| Go-CQHTTP | `set_qq_profile` | 设置QQ资料 | ✅️ | `qq_account_manage.set_profile` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1061) | 只声明 nickname、personal_note、sex；插件允许的 `company`、`email`、`college` 不会被处理。 |
| Go-CQHTTP | `upload_group_file` | 上传群文件 | ✅️ | `qq_group_files.upload` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L21) | 上传群文件。主要参数：group_id、file、name、folder、folder_id、upload_file。返回说明：{ file_id: string }。 |
| Go-CQHTTP | `upload_private_file` | 上传私聊文件 | ✅️ | `qq_private_files.upload` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-file.ts#L42) | 支持 user_id、file、name、upload_file；默认完成上传后发送文件消息，返回 {file_id}。 |
| 流式接口 | `download_file_stream` | 下载文件流 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-download.ts#L360) | 有流式下载实现，发送 file_info → file_chunk → file_complete；来源为受控 stream 目录、URL 或缓存媒体，需要流式帧接收能力。 |
| 流式接口 | `upload_file_stream` | 上传文件流 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-file.ts#L348) | 有分块上传、校验、合并及保留期限实现；返回分块确认与完成帧，不是普通单响应文件上传。 |
| 流式传输扩展 | `clean_stream_temp_file` | 清理流式传输临时文件 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-file.ts#L373) | 真实清理不活跃的 stream 临时项，返回 removed、freed_bytes、skipped_active；删除失败会报错。 |
| 流式传输扩展 | `download_file_image_stream` | 下载图片文件流 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-download.ts#L368) | 接受缓存图片 ID、URL 或受控 stream 目录文件，实际推送图片下载数据帧，需要流式接收能力。 |
| 流式传输扩展 | `download_file_record_stream` | 下载语音文件流 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-download.ts#L376) | 接受缓存语音 ID、URL 或受控 stream 目录文件，实际推送语音下载数据帧，需要流式接收能力。 |
| 流式传输扩展 | `test_download_stream` | 测试下载流 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/stream-download.ts#L384) | 推送 10 个测试数据帧与完成帧；error=true 测试错误结束，不调用 QQ。 |
| 扩展接口 | `create_collection` | 创建收藏 | ❌️ | — | [❌️ 已注册但拒绝](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2048) | 名称已注册，但固定返回 ACTION_FAILED / not yet implemented；没有创建收藏实现。 |
| 扩展接口 | `delete_qzone_msg` | 删除QQ空间说说 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/qzone.ts#L139) | 删除一条说说（QQ 空间，按 tid）。主要参数：tid。 |
| 扩展接口 | `get_ai_characters` | 获取AI角色列表 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2231) | 获取 AI 语音角色。主要参数：group_id、chat_type。返回说明：按分类分组的 AI 语音角色列表，每组含分类名与角色（id、名称、试听 URL）。 |
| 扩展接口 | `get_clientkey` | 获取ClientKey | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L1718) | 获取 clientkey。返回说明：{ clientKey, expireTime, keyIndex }：clientkey 及其过期时间与索引。 |
| 扩展接口 | `send_qzone_msg` | 发表QQ空间说说 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/qzone.ts#L114) | 发表说说（QQ 空间，支持纯文字或带图；传 images 自动上传；可设置查看权限）。主要参数：content、images、ugc_right、target_uins。 |
| 扩展接口 | `set_group_kick_members` | 批量踢出群成员 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L16) | 批量踢出群成员。主要参数：group_id、user_id、reject_add_request。 |
| 扩展接口 | `set_group_special_title` | 设置专属头衔 | ✅️ | `qq_group_member_manage.title` | [⚠️ 参数受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/group-admin.ts#L263) | 可设置 special_title；不声明插件可传的 `duration`，无法按该参数控制头衔期限。 |
| 扩展接口 | `set_qq_avatar` | 设置QQ头像 | ✅️ | `qq_account_manage.set_avatar` | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2067) | 设置 QQ 头像。主要参数：file。 |
| 扩展接口 | `set_self_longnick` | 设置个性签名 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2631) | 设置个性签名（longNick/long_nick，严格 string）。主要参数：longNick、long_nick。 |
| 扩展接口 | `translate_en2zh` | 英文单词翻译 | ❌️ | — | [✅️ 有实现](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2612) | 英译中。主要参数：words。返回说明：{ words }：与输入等长的中文译文字符串数组。 |
| 测试接口 | `test_auto_register_01` | 自动注册路由测试 1 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称；属于原表中的 NapCat 路由测试动作。 |
| 测试接口 | `test_auto_register_02` | 自动注册路由测试 2 | ❌️ | — | [❌️ 未注册](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts#L250) | 统一动作注册表没有此名称；属于原表中的 NapCat 路由测试动作。 |
| 其他接口 | `.ocr_image` | 图片 OCR 识别 (内部) | ❌️ | — | [⚠️ 别名／输入受限](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/extended.ts#L2396) | 已注册为 `ocr_image` 的别名；同样只接受图片 URL 或缓存图片 ID，不接受插件当前生成的本地路径。 |


## 当前适配状态

已新增独立的 [SnowLuma provider](../providers/snowluma.py) 和 [v1.14.22 动作契约](../contracts/snowluma_v1_14_22.json)，运行时及诊断通过统一识别流程接入，接受 `>=1.14.22` 的版本，版本标识可为 `x.y.z` / `x.y.z-node`，且要求协议为 `v11`。原表保留最初的源码核对记录，当前用户入口以 [README 的支持范围](../README.md#snowluma-支持范围) 为准。

1. **动作注册与实际能力分别判断。** 74 个契约名称均已注册；最近联系人占位和扩展群资料入口禁用，在执行、工具筛选和诊断中使用相同判定。
2. **群文件移动已转换目录参数。** 公开的 `current_parent_directory` / `target_parent_directory` 转为 `parent_directory` / `target_directory`。
3. **历史锚点按实现区分。** SnowLuma 使用允许负数的 `message_id`；NapCat 使用 `message_seq`。错用或混用明确报错，不做语义不等价的改名。
4. **OCR 按输入语义接入。** SnowLuma 只开放 URL 和缓存图片 `file_id`，URL 通过现有网络校验后转发最终地址；本地路径、Base64 和 `media_ref` 明确拒绝。结构化 `texts` 结果支持分页。
5. **转码结果单独保存。** SnowLuma 返回的转码 Base64 经大小和编码检查后生成可复用的 `media_ref`，返回生成文件的实际大小，不保留错误指向源语音的文件名、大小或下载地址。
6. **不生效的扩展参数明确拒绝。** 包括好友审批 `remark`、资料 `company/email/college`、头衔 `duration`、公告 `title`、强制刷新 `no_cache=true`、解散群 `is_dismiss=true` 和群头像 `cache=true`。
7. **查询限制随能力提供。** 设备快照、成员资料固定值、禁言缓存延迟会出现在工具结果和诊断中；群申请数组仍按已授权群过滤。私聊文件下载保留 `user_id`，支持显式 `file_hash`。
8. **确认记录绑定协议实现。** 确认前重新识别并检查版本，拒绝实现变化或缺少实现标识的记录，需重新发起。
9. **骰子与猜拳结果。** 识别 `face.id=358/359` 为骰子／猜拳，读取 `data.resultId`：骰子为 1–6 点，猜拳为 1=布、2=剪刀、3=石头。入站描述、组件验证和发送后回查使用同一解析逻辑。

   SnowLuma 的自发消息缓存可能缺少结果。`get_msg` 未取得完整结果时，私聊使用 `message_id=0,count=20` 获取最新服务器漫游历史，避免带锚点的单条查询返回更早的文字消息；群聊按本次 `message_id` 查询一条历史。两者均只采纳消息编号、机器人发送人和会话均匹配的记录，临时会话不使用好友历史补查。

   服务器漫游历史可能延迟包含刚发出的消息。补查未找到目标消息或目标结果尚不完整时，按 0.5、1、2、4 秒的间隔重试，最多查询 5 次，包含首次 `get_msg` 在内的结果回查总等待上限为 10 秒。取得全部结果立即结束；接口报错或响应格式无效时停止重试。日志记录尝试次数、耗时和命中情况，只在最终补查失败时输出一次警告。结果缺失、越界或目标消息不在返回范围内时不推算、不借用其他消息的结果；失败或仅取得部分结果时保留工具警告，不重复发送。

   用户样本：骰子 `395675369` 的 `get_msg` 只有 `id=358`，同一消息的好友历史包含 `resultId=6`；猜拳 `1216507570` 的带锚点单条查询返回文字消息 `1873809679`，手动漫游查询找到原消息及 `resultId=3`（石头）。2026-10-15 17:33 日志中，发送约 0.2 秒后的漫游历史未包含本次消息，约 21 秒后的下一次查询已包含上一局猜拳 `677311847`，证明存在延迟可见，但不能据此确定实际延迟为 21 秒。

   在线验证：用户于 2026-10-15 17:39–17:40 提供的日志确认，修改后的私聊自动补查已成功。猜拳 `-1182177453` 返回“剪刀”，回查耗时 703 毫秒；骰子 `-104008777` 返回 1 点，回查耗时 639 毫秒。两次均为第二次历史查询命中，`resolved=1/1`，工具返回完整 `random_results` 且 `warnings=[]`。这些耗时为本次样本值；群聊补查尚待 QQ 实测。

适配包含离线回归测试；当前在线验证记录见上文骰子与猜拳条目。

## 平台事件支持情况

以下按同一固定版本 v1.14.22 的事件注册、协议解析及 OneBot 转换代码核对。插件的 19 类平台事件中，16 类已接入，3 类因上游未上报而无法接入；“已接入”经过离线回归验证，不代表已在 QQ 逐项实测。事件是否写入历史仍由 `notice_events` 的各项模式决定。

| 事件标识 | SnowLuma 支持情况 | 简要说明 |
| --- | --- | --- |
| `notify/poke` | 已接入 | 按被戳对象分别选择模式：机器人被戳默认 `respond`，其他用户被戳默认 `context`；忽略机器人主动戳人。统一使用平台事件格式、`notice` 防伪类型和 `off` / `context` / `respond` 模式。 |
| `friend_add` | 已接入 | 使用好友添加成功上报。 |
| `message_recall` | 已接入 | 接收 `friend_recall` / `group_recall`，允许负数消息 ID；仍须命中插件保存的原消息映射。 |
| `group_increase` | 已接入 | 支持审批入群和邀请入群。 |
| `group_decrease` | 已接入 | 支持退出、被踢、机器人被踢及群解散。 |
| `group_admin` | 已接入 | 支持设置和取消管理员。 |
| `group_ban` | 已接入 | 支持成员及全员禁言变化，按上报子类型和时长记录。 |
| `group_card` | 已接入 | 上游在成员发言时比较非空的新旧名片；冷缓存、空名片变化可能不产生通知。 |
| `notify/group_name` | 已接入 | 使用上报的新群名。 |
| `notify/title` | 已接入 | 使用上报的成员及新头衔。 |
| `essence` | 已接入 | 支持添加和移除精华，保留消息 ID、作者及操作者。 |
| `group_msg_emoji_like` | 已接入 | 将 `sub_type=add/remove` 规范化为增减；保留数字和字母数字表情标识，数量只按原值展示。 |
| `notify/profile_like` | 已接入 | 按 `operator_id` 定位私聊，记录上报的点赞次数。 |
| `notify/gray_tip` | 无法接入 | 上游仅解析部分已知灰条，不上报未知灰条原文，插件没有可用事件数据。 |
| `notify/input_status` | 已接入 | 接受不带 `group_id` 的私聊上报；保留原始状态码及文本，不推断状态含义。 |
| `group_upload` | 已接入 | 记录上传者及文件元数据，不读取文件内容。 |
| `online_file_receive` | 无法接入 | 上游没有在线文件取消事件；普通文件消息不能证明传输已取消。 |
| `online_file_send` | 无法接入 | 上游没有在线文件接收或拒绝事件；发送成功不能证明对方已接收。 |
| `bot_offline` | 已接入 | 接收带原因的 `bot_offline`，同时将 `bot_status/offline` 作为无原因的离线事实，投递到原配置的接收者；不处理上线通知。 |

字段适配直接使用两种协议端当前的上报格式，不新增配置。缺少方向或方向冲突的表情回应、错误的私聊群号、机器人账号不匹配的离线通知仍会拒绝，不从表情数量、心跳或普通消息推测事件。

核对依据：[OneBot 事件注册表](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/event-converter/index.ts#L79)、[通知字段转换](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/event-converter/to-notice.ts#L27)、[离线状态通知](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/instance.ts#L688)、[群名片变化触发条件](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/protocol/src/packet-pipeline.ts#L362)、[群灰条解析范围](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/protocol/src/msg-push/decoders/event-0x2dc.ts#L81)。

## 核对来源

- [统一动作注册表及分组绑定](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/actions/index.ts)：普通动作、别名、流式动作及 raw action 的注册依据。
- [动作参数解析与处理器生成](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/action-kit.ts#L491)：只解析已声明参数、校验并执行处理器。
- [API 动作分派](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/api-handler.ts#L236)：未注册动作返回 UNKNOWN_ACTION；快速操作由 raw handler 执行。
- [运行上下文绑定](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/instance-context.ts)：动作到真实查询、发送、媒体等模块的绑定。
- [媒体查询与语音转写](https://github.com/SnowLuma/SnowLuma/blob/87527cb7641a5a42f8f0efb73cb066102e004dee/packages/onebot/src/modules/media-actions.ts)：缓存媒体解析、返回字段和语音转写依赖。
- [原始能力表](./Capabilities_NapCat.md)、[插件动作与参数声明](../catalog.py)、[插件运行时](../runtime.py)：保留原表并核对当前插件的参数组装、结果过滤及媒体引用行为。
