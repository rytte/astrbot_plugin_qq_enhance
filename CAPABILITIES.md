# NapCat 与 QQ 扩展工具插件能力矩阵

> 生成日期：2026-09-03
>
> 对比基线：插件契约指定的 NapCat 4.18.19、本机 `NapCat.Shell/napcat.mjs` 实际动作处理器，以及当前 `astrbot_plugin_qq_extension_tools` 源码。

## 统计

| 项目 | 数量 |
|---|---:|
| NapCat 已注册动作 | 177 |
| 插件公开能力 | 26 个工具、77 个操作 |
| 插件覆盖的 NapCat 动作 | 71 |

统计口径：NapCat 数量来自实际注册的动作处理器，不计 `unknown` 和没有处理器的 `.get_word_slices`；插件覆盖数由 67 个直接映射动作和 4 个安全封装发送动作组成。

状态说明：

- **✅️**：插件存在直接公开的 `tool.operation` 映射。
- **⚠️ 受限封装**：插件会调用该动作，但只开放经过目标、参数、权限或组件校验的子集。
- **❌️**：当前插件没有向模型公开该动作。

“NapCat 已注册”只表示动作处理器存在，不保证相关 QQ 能力在所有账号、客户端版本和服务端策略下成功。发送动作返回成功也只证明 NapCat 接受了请求，不能单独证明接收端可展示。

## NapCat 全部动作与插件覆盖

| 分类 | NapCat 动作 | NapCat 能力 | 插件支持 | 插件入口 |
|---|---|---|---|---|
| 核心接口 | `friend_poke` | 私聊戳一戳 | ✅️ | `qq_friend_interact.poke` |
| 核心接口 | `group_poke` | 群聊戳一戳 | ✅️ | `qq_group_member_manage.poke` |
| 核心接口 | `send_poke` | 发送戳一戳 | ❌️ | — |
| 系统接口 | `can_send_image` | 是否可以发送图片 | ❌️ | — |
| 系统接口 | `can_send_record` | 是否可以发送语音 | ❌️ | — |
| 系统接口 | `clean_cache` | 清理缓存 | ❌️ | — |
| 系统接口 | `get_credentials` | 获取登录凭证 | ❌️ | — |
| 系统接口 | `get_csrf_token` | 获取 CSRF Token | ❌️ | — |
| 系统接口 | `get_doubt_friends_add_request` | 获取可疑好友申请 | ❌️ | — |
| 系统接口 | `get_group_system_msg` | 获取群系统消息 | ✅️ | `qq_group_request.list` |
| 系统接口 | `get_login_info` | 获取登录号信息 | ✅️ | `qq_status.login` |
| 系统接口 | `get_status` | 获取运行状态 | ✅️ | `qq_status.runtime` |
| 系统接口 | `get_version_info` | 获取版本信息 | ✅️ | `qq_status.version` |
| 系统接口 | `nc_get_packet_status` | 获取Packet状态 | ❌️ | — |
| 系统接口 | `set_doubt_friends_add_request` | 处理可疑好友申请 | ❌️ | — |
| 系统接口 | `set_restart` | 重启服务 | ❌️ | — |
| 系统扩展 | `add_custom_face` | 添加自定义表情 | ❌️ | — |
| 系统扩展 | `bot_exit` | 退出登录 | ❌️ | — |
| 系统扩展 | `delete_custom_face` | 删除自定义表情 | ❌️ | — |
| 系统扩展 | `fetch_custom_face` | 获取自定义表情 | ❌️ | — |
| 系统扩展 | `fetch_custom_face_detail` | 获取自定义表情详情 | ❌️ | — |
| 系统扩展 | `get_collection_list` | 获取收藏列表 | ❌️ | — |
| 系统扩展 | `get_mini_app_ark` | 获取小程序 Ark | ❌️ | — |
| 系统扩展 | `get_rkey` | 获取扩展 RKey | ❌️ | — |
| 系统扩展 | `get_rkey_server` | 获取 RKey 服务器 | ❌️ | — |
| 系统扩展 | `get_robot_uin_range` | 获取机器人 UIN 范围 | ❌️ | — |
| 系统扩展 | `nc_get_rkey` | 获取 RKey | ❌️ | — |
| 系统扩展 | `nc_get_user_status` | 获取用户在线状态 | ❌️ | — |
| 系统扩展 | `send_packet` | 发送原始数据包 | ❌️ | — |
| 系统扩展 | `set_custom_face_desc` | 修改自定义表情描述 | ❌️ | — |
| 系统扩展 | `set_input_status` | 设置输入状态 | ❌️ | — |
| 系统扩展 | `set_online_status` | 设置在线状态 | ✅️ | `qq_account_manage.set_online_status` |
| 用户接口 | `get_cookies` | 获取 Cookies | ❌️ | — |
| 用户接口 | `get_friend_list` | 获取好友列表 | ✅️ | `qq_friend_list.friends` |
| 用户接口 | `get_recent_contact` | 获取最近会话 | ✅️ | `qq_recent_contacts.list` |
| 用户接口 | `send_like` | 点赞 | ✅️ | `qq_friend_interact.like` |
| 用户接口 | `set_friend_add_request` | 处理加好友请求 | ✅️ | `qq_friend_request.approve`<br>`qq_friend_request.reject` |
| 用户接口 | `set_friend_remark` | 设置好友备注 | ✅️ | `qq_friend_manage.set_remark` |
| 用户扩展 | `get_friends_with_category` | 获取带分组的好友列表 | ❌️ | — |
| 用户扩展 | `get_profile_like` | 获取资料点赞 | ❌️ | — |
| 用户扩展 | `get_unidirectional_friend_list` | 获取单向好友列表 | ✅️ | `qq_friend_list.unidirectional` |
| 用户扩展 | `set_diy_online_status` | 设置自定义在线状态 | ❌️ | — |
| 群组接口 | `_del_group_notice` | 删除群公告 | ✅️ | `qq_notice.delete` |
| 群组接口 | `_get_group_notice` | 获取群公告 | ✅️ | `qq_notice.detail`<br>`qq_notice.list` |
| 群组接口 | `delete_essence_msg` | 移出精华消息 | ✅️ | `qq_essence.remove` |
| 群组接口 | `get_essence_msg_list` | 获取群精华消息 | ✅️ | `qq_essence.list` |
| 群组接口 | `get_group_detail_info` | 获取群详细信息 | ❌️ | — |
| 群组接口 | `get_group_ignore_add_request` | 获取群被忽略的加群请求 | ❌️ | — |
| 群组接口 | `get_group_ignored_notifies` | 获取群忽略通知 | ✅️ | `qq_group_request.ignored` |
| 群组接口 | `get_group_info` | 获取群信息 | ✅️ | `qq_group_info.detail` |
| 群组接口 | `get_group_list` | 获取群列表 | ✅️ | `qq_group_list.list` |
| 群组接口 | `get_group_member_info` | 获取群成员信息 | ✅️ | `qq_group_members.detail`<br>`qq_user_info.group_member` |
| 群组接口 | `get_group_member_list` | 获取群成员列表 | ✅️ | `qq_group_members.list` |
| 群组接口 | `get_group_shut_list` | 获取群禁言列表 | ✅️ | `qq_group_info.mute_list` |
| 群组接口 | `send_group_msg` | 发送群消息 | ⚠️ 受限封装 | `qq_send_message.send` |
| 群组接口 | `set_essence_msg` | 设置精华消息 | ✅️ | `qq_essence.add` |
| 群组接口 | `set_group_add_request` | 处理加群请求 | ✅️ | `qq_group_request.approve`<br>`qq_group_request.reject` |
| 群组接口 | `set_group_admin` | 设置群管理员 | ✅️ | `qq_group_member_manage.admin` |
| 群组接口 | `set_group_ban` | 群组禁言 | ✅️ | `qq_group_member_manage.ban` |
| 群组接口 | `set_group_card` | 设置群名片 | ✅️ | `qq_group_member_manage.card` |
| 群组接口 | `set_group_kick` | 群组踢人 | ✅️ | `qq_group_member_manage.kick` |
| 群组接口 | `set_group_leave` | 退出群组 | ✅️ | `qq_group_manage.leave` |
| 群组接口 | `set_group_member_invite_policy` | 设置群成员邀请策略 | ❌️ | — |
| 群组接口 | `set_group_member_permissions` | 设置群成员功能权限 | ❌️ | — |
| 群组接口 | `set_group_name` | 设置群名称 | ✅️ | `qq_group_manage.name` |
| 群组接口 | `set_group_new_member_history_visibility` | 设置新成员历史消息可见性 | ❌️ | — |
| 群组接口 | `set_group_whole_ban` | 全员禁言 | ✅️ | `qq_group_manage.whole_ban` |
| 群组扩展 | `cancel_group_album_media_like` | 取消点赞群相册媒体 | ❌️ | — |
| 群组扩展 | `cancel_group_todo` | 取消群待办 | ❌️ | — |
| 群组扩展 | `complete_group_todo` | 完成群待办 | ❌️ | — |
| 群组扩展 | `del_group_album_media` | 删除群相册媒体 | ❌️ | — |
| 群组扩展 | `do_group_album_comment` | 发表群相册评论 | ❌️ | — |
| 群组扩展 | `get_group_album_media_list` | 获取群相册媒体列表 | ❌️ | — |
| 群组扩展 | `get_group_info_ex` | 获取群详细信息 (扩展) | ✅️ | `qq_group_info.detail_ex` |
| 群组扩展 | `get_group_signed_list` | 获取群组今日打卡列表 | ❌️ | — |
| 群组扩展 | `get_qun_album_list` | 获取群相册列表 | ❌️ | — |
| 群组扩展 | `send_group_sign` | 群打卡 | ❌️ | — |
| 群组扩展 | `set_group_add_option` | 设置群加群选项 | ❌️ | — |
| 群组扩展 | `set_group_album_media_like` | 点赞群相册媒体 | ❌️ | — |
| 群组扩展 | `set_group_remark` | 设置群备注 | ❌️ | — |
| 群组扩展 | `set_group_robot_add_option` | 设置群机器人加群选项 | ❌️ | — |
| 群组扩展 | `set_group_search` | 设置群搜索选项 | ❌️ | — |
| 群组扩展 | `set_group_sign` | 群打卡 | ✅️ | `qq_group_manage.sign` |
| 群组扩展 | `set_group_todo` | 设置群待办 | ❌️ | — |
| 群组扩展 | `upload_image_to_qun_album` | 上传图片到群相册 | ❌️ | — |
| 消息接口 | `_mark_all_as_read` | 标记所有消息已读 | ❌️ | — |
| 消息接口 | `delete_msg` | 撤回消息 | ✅️ | `qq_message_manage.recall` |
| 消息接口 | `forward_friend_single_msg` | 转发单条消息到好友 | ❌️ | — |
| 消息接口 | `forward_group_single_msg` | 转发单条消息到群 | ❌️ | — |
| 消息接口 | `get_msg` | 获取消息 | ✅️ | `qq_message_get.get` |
| 消息接口 | `mark_group_msg_as_read` | 标记群聊已读 | ❌️ | — |
| 消息接口 | `mark_msg_as_read` | 标记消息已读 (Go-CQHTTP) | ✅️ | `qq_message_manage.mark_read` |
| 消息接口 | `mark_private_msg_as_read` | 标记私聊已读 | ❌️ | — |
| 消息接口 | `send_msg` | 发送消息 | ❌️ | — |
| 消息接口 | `send_private_msg` | 发送私聊消息 | ⚠️ 受限封装 | `qq_send_message.send` |
| 消息扩展 | `ArkShareGroup` | 获取群推荐 Ark（旧别名，仅返回数据） | ❌️ | — |
| 消息扩展 | `ArkSharePeer` | 获取用户或群推荐 Ark（旧别名，仅返回数据） | ❌️ | — |
| 消息扩展 | `click_inline_keyboard_button` | 点击内联键盘按钮 | ❌️ | — |
| 消息扩展 | `fetch_emoji_like` | 获取表情点赞详情 | ❌️ | — |
| 消息扩展 | `fetch_ptt_text` | 获取语音转文字结果 | ❌️ | — |
| 消息扩展 | `get_emoji_likes` | 获取消息表情点赞列表 | ❌️ | — |
| 消息扩展 | `send_ark_share` | 获取用户或群推荐 Ark（标准名，仅返回数据） | ❌️ | — |
| 消息扩展 | `send_group_ark_share` | 获取群推荐 Ark（标准名，仅返回数据） | ❌️ | — |
| 消息扩展 | `set_msg_emoji_like` | 设置消息表情点赞 | ✅️ | `qq_message_manage.reaction_add`<br>`qq_message_manage.reaction_remove` |
| 文件接口 | `get_file` | 获取文件 | ❌️ | — |
| 文件接口 | `get_group_file_url` | 获取群文件URL | ✅️ | `qq_group_files.url` |
| 文件接口 | `get_image` | 获取图片 | ✅️ | `qq_media.get_image` |
| 文件接口 | `get_private_file_url` | 获取私聊文件URL | ✅️ | `qq_private_files.url` |
| 文件接口 | `get_record` | 获取语音 | ✅️ | `qq_media.convert_record`<br>`qq_media.get_record` |
| 文件接口 | `ocr_image` | 图片 OCR 识别 | ✅️ | `qq_media.ocr` |
| 文件扩展 | `cancel_online_file` | 取消在线文件 | ❌️ | — |
| 文件扩展 | `create_flash_task` | 创建闪传任务 | ❌️ | — |
| 文件扩展 | `download_fileset` | 下载文件集 | ❌️ | — |
| 文件扩展 | `get_fileset_id` | 获取文件集 ID | ❌️ | — |
| 文件扩展 | `get_fileset_info` | 获取文件集信息 | ❌️ | — |
| 文件扩展 | `get_flash_file_list` | 获取闪传文件列表 | ❌️ | — |
| 文件扩展 | `get_flash_file_url` | 获取闪传文件链接 | ❌️ | — |
| 文件扩展 | `get_online_file_msg` | 获取在线文件消息 | ❌️ | — |
| 文件扩展 | `get_share_link` | 获取文件分享链接 | ❌️ | — |
| 文件扩展 | `move_group_file` | 移动群文件 | ✅️ | `qq_group_files.move` |
| 文件扩展 | `receive_online_file` | 接收在线文件 | ❌️ | — |
| 文件扩展 | `refuse_online_file` | 拒绝在线文件 | ❌️ | — |
| 文件扩展 | `rename_group_file` | 重命名群文件 | ✅️ | `qq_group_files.rename` |
| 文件扩展 | `send_flash_msg` | 发送闪传消息 | ❌️ | — |
| 文件扩展 | `send_online_file` | 发送在线文件 | ❌️ | — |
| 文件扩展 | `send_online_folder` | 发送在线文件夹 | ❌️ | — |
| 文件扩展 | `trans_group_file` | 传输群文件 | ✅️ | `qq_group_files.transfer` |
| AI 扩展 | `get_ai_record` | 获取 AI 语音 | ❌️ | — |
| AI 扩展 | `send_group_ai_record` | 发送群 AI 语音 | ❌️ | — |
| 频道接口 | `get_guild_list` | 获取频道列表 | ❌️ | — |
| 频道接口 | `get_guild_service_profile` | 获取频道个人信息 | ❌️ | — |
| Go-CQHTTP | `.handle_quick_operation` | 处理快速操作 | ❌️ | — |
| Go-CQHTTP | `_get_model_show` | 获取机型显示 | ❌️ | — |
| Go-CQHTTP | `_send_group_notice` | 发送群公告 | ✅️ | `qq_notice.send` |
| Go-CQHTTP | `_set_model_show` | 设置机型 | ❌️ | — |
| Go-CQHTTP | `check_url_safely` | 检查URL安全性 | ❌️ | — |
| Go-CQHTTP | `create_group_file_folder` | 创建群文件目录 | ✅️ | `qq_group_files.mkdir` |
| Go-CQHTTP | `delete_friend` | 删除好友 | ✅️ | `qq_friend_manage.delete` |
| Go-CQHTTP | `delete_group_file` | 删除群文件 | ✅️ | `qq_group_files.delete` |
| Go-CQHTTP | `delete_group_folder` | 删除群文件目录 | ✅️ | `qq_group_files.rmdir` |
| Go-CQHTTP | `download_file` | 下载文件 | ❌️ | — |
| Go-CQHTTP | `get_forward_msg` | 获取合并转发消息 | ✅️ | `qq_forward_get.get` |
| Go-CQHTTP | `get_friend_msg_history` | 获取好友历史消息 | ✅️ | `qq_friend_history.list` |
| Go-CQHTTP | `get_group_at_all_remain` | 获取群艾特全体剩余次数 | ✅️ | `qq_group_info.at_all_remain` |
| Go-CQHTTP | `get_group_file_system_info` | 获取群文件系统信息 | ✅️ | `qq_group_files.info` |
| Go-CQHTTP | `get_group_files_by_folder` | 获取群文件夹文件列表 | ✅️ | `qq_group_files.list_folder` |
| Go-CQHTTP | `get_group_honor_info` | 获取群荣誉信息 | ✅️ | `qq_group_info.honor` |
| Go-CQHTTP | `get_group_msg_history` | 获取群历史消息 | ✅️ | `qq_group_history.list` |
| Go-CQHTTP | `get_group_root_files` | 获取群根目录文件列表 | ✅️ | `qq_group_files.list_root` |
| Go-CQHTTP | `get_online_clients` | 获取在线客户端 | ✅️ | `qq_status.clients` |
| Go-CQHTTP | `get_stranger_info` | 获取陌生人信息 | ✅️ | `qq_user_info.stranger` |
| Go-CQHTTP | `send_forward_msg` | 发送合并转发消息 | ❌️ | — |
| Go-CQHTTP | `send_group_forward_msg` | 发送群合并转发消息 | ⚠️ 受限封装 | `qq_send_forward.send` |
| Go-CQHTTP | `send_private_forward_msg` | 发送私聊合并转发消息 | ⚠️ 受限封装 | `qq_send_forward.send` |
| Go-CQHTTP | `set_group_portrait` | 设置群头像 | ✅️ | `qq_group_manage.avatar` |
| Go-CQHTTP | `set_qq_profile` | 设置QQ资料 | ✅️ | `qq_account_manage.set_profile` |
| Go-CQHTTP | `upload_group_file` | 上传群文件 | ✅️ | `qq_group_files.upload` |
| Go-CQHTTP | `upload_private_file` | 上传私聊文件 | ✅️ | `qq_private_files.upload` |
| 流式接口 | `download_file_stream` | 下载文件流 | ❌️ | — |
| 流式接口 | `upload_file_stream` | 上传文件流 | ❌️ | — |
| 流式传输扩展 | `clean_stream_temp_file` | 清理流式传输临时文件 | ❌️ | — |
| 流式传输扩展 | `download_file_image_stream` | 下载图片文件流 | ❌️ | — |
| 流式传输扩展 | `download_file_record_stream` | 下载语音文件流 | ❌️ | — |
| 流式传输扩展 | `test_download_stream` | 测试下载流 | ❌️ | — |
| 扩展接口 | `create_collection` | 创建收藏 | ❌️ | — |
| 扩展接口 | `delete_qzone_msg` | 删除QQ空间说说 | ❌️ | — |
| 扩展接口 | `get_ai_characters` | 获取AI角色列表 | ❌️ | — |
| 扩展接口 | `get_clientkey` | 获取ClientKey | ❌️ | — |
| 扩展接口 | `send_qzone_msg` | 发表QQ空间说说 | ❌️ | — |
| 扩展接口 | `set_group_kick_members` | 批量踢出群成员 | ❌️ | — |
| 扩展接口 | `set_group_special_title` | 设置专属头衔 | ✅️ | `qq_group_member_manage.title` |
| 扩展接口 | `set_qq_avatar` | 设置QQ头像 | ✅️ | `qq_account_manage.set_avatar` |
| 扩展接口 | `set_self_longnick` | 设置个性签名 | ❌️ | — |
| 扩展接口 | `translate_en2zh` | 英文单词翻译 | ❌️ | — |
| 测试接口 | `test_auto_register_01` | 自动注册路由测试 1 | ❌️ | — |
| 测试接口 | `test_auto_register_02` | 自动注册路由测试 2 | ❌️ | — |
| 其他接口 | `.ocr_image` | 图片 OCR 识别 (内部) | ❌️ | — |

## 插件公开工具与操作

| 工具 | 公开操作 | 对应 NapCat 动作或实现 |
|---|---|---|
| `qq_status` | `login`、`runtime`、`version`、`clients`、`capabilities` | `get_login_info`<br>`get_online_clients`<br>`get_status`<br>`get_version_info`<br>本地编排：`capabilities` |
| `qq_account_manage` | `set_profile`、`set_avatar`、`set_online_status` | `set_online_status`<br>`set_qq_avatar`<br>`set_qq_profile` |
| `qq_user_info` | `stranger`、`group_member` | `get_group_member_info`<br>`get_stranger_info` |
| `qq_friend_list` | `friends`、`unidirectional` | `get_friend_list`<br>`get_unidirectional_friend_list` |
| `qq_friend_history` | `list` | `get_friend_msg_history` |
| `qq_friend_interact` | `like`、`poke` | `friend_poke`<br>`send_like` |
| `qq_friend_request` | `list`、`approve`、`reject` | `set_friend_add_request`<br>本地编排：`list` |
| `qq_friend_manage` | `delete`、`set_remark` | `delete_friend`<br>`set_friend_remark` |
| `qq_group_list` | `list` | `get_group_list` |
| `qq_group_info` | `detail`、`detail_ex`、`honor`、`at_all_remain`、`mute_list` | `get_group_at_all_remain`<br>`get_group_honor_info`<br>`get_group_info`<br>`get_group_info_ex`<br>`get_group_shut_list` |
| `qq_group_members` | `list`、`detail` | `get_group_member_info`<br>`get_group_member_list` |
| `qq_group_history` | `list` | `get_group_msg_history` |
| `qq_group_request` | `list`、`ignored`、`approve`、`reject` | `get_group_ignored_notifies`<br>`get_group_system_msg`<br>`set_group_add_request` |
| `qq_group_member_manage` | `poke`、`card`、`title`、`ban`、`kick`、`admin` | `group_poke`<br>`set_group_admin`<br>`set_group_ban`<br>`set_group_card`<br>`set_group_kick`<br>`set_group_special_title` |
| `qq_group_manage` | `whole_ban`、`name`、`avatar`、`sign`、`leave` | `set_group_leave`<br>`set_group_name`<br>`set_group_portrait`<br>`set_group_sign`<br>`set_group_whole_ban` |
| `qq_send_message` | `send` | `send_group_msg`<br>`send_private_msg`<br>本地编排：`send` |
| `qq_send_forward` | `send` | `send_group_forward_msg`<br>`send_private_forward_msg`<br>本地编排：`send` |
| `qq_message_get` | `get` | `get_msg` |
| `qq_forward_get` | `get` | `get_forward_msg` |
| `qq_message_manage` | `recall`、`mark_read`、`reaction_add`、`reaction_remove` | `delete_msg`<br>`mark_msg_as_read`<br>`set_msg_emoji_like` |
| `qq_recent_contacts` | `list` | `get_recent_contact` |
| `qq_media` | `get_image`、`get_record`、`convert_record`、`ocr` | `get_image`<br>`get_record`<br>`ocr_image` |
| `qq_group_files` | `info`、`list_root`、`list_folder`、`url`、`upload`、`mkdir`、`delete`、`rmdir`、`move`、`rename`、`transfer` | `create_group_file_folder`<br>`delete_group_file`<br>`delete_group_folder`<br>`get_group_file_system_info`<br>`get_group_file_url`<br>`get_group_files_by_folder`<br>`get_group_root_files`<br>`move_group_file`<br>`rename_group_file`<br>`trans_group_file`<br>`upload_group_file` |
| `qq_private_files` | `url`、`upload` | `get_private_file_url`<br>`upload_private_file` |
| `qq_essence` | `list`、`add`、`remove` | `delete_essence_msg`<br>`get_essence_msg_list`<br>`set_essence_msg` |
| `qq_notice` | `list`、`detail`、`send`、`delete` | `_del_group_notice`<br>`_get_group_notice`<br>`_send_group_notice` |

## 发送消息组件

这一表按实际转换代码评估，特意区分“Schema 接受”和“能够正确发送/展示”。

| 组件 | NapCat 4.18.19 实际状态 | 当前插件状态 | 结论与限制 |
|---|---|---|---|
| `text` | 已实现 | 支持 | 普通文本 |
| `image` | 已实现 | 支持 | 插件要求 path、url、base64、media_ref 四选一 |
| `music` | 依赖外部签名服务 | 条件支持 | qq_search、平台 ID 或 custom；最终成功取决于 musicSignUrl |
| `video` | 已实现 | 支持 | 插件使用统一受控媒体来源 |
| `record` | 已实现 | 支持 | 语音消息 |
| `file` | 已实现 | 支持 | 文件消息；具体会话限制由 NapCat/QQ 决定 |
| `at` | 已实现 | 支持 | 主要用于群聊 |
| `reply` | 已实现 | 支持 | 引用消息 ID 必须有效 |
| `json` | 原样转为 Ark bytesData | 透传支持 | 必须是上游正式接口生成的完整有效 Ark；任意语法正确的 JSON 不等于有效卡片 |
| `face` | 已实现 | 支持 | QQ 表情 |
| `mface` | 已实现 | 不支持 | NapCat 支持商城表情，插件未开放 |
| `markdown` | 已构造元素，但标注需要签名 | 不支持 | 不能视为任意账号均可直接发送 |
| `node` | 通用发送转换器为空 | 不作为普通组件支持 | 插件仅在 qq_send_forward.send 的自定义转发节点中支持节点语义 |
| `forward` | 可将 res_id 转为 Ark | 不作为普通组件支持 | 插件通过独立的 qq_send_forward.send 发送合并转发 |
| `xml` | 转换器为空 | 不支持 | 当前版本不能据此认定可发送 |
| `poke` | 消息段转换器为空 | 通过独立操作支持 | 使用 qq_friend_interact.poke 或 qq_group_member_manage.poke |
| `dice` | 已实现 | 支持 | 骰子表情 |
| `rps` | 已实现 | 支持 | 猜拳表情 |
| `miniapp` | 消息段转换器为空 | 不支持 | NapCat 另有 get_mini_app_ark 生成动作，但插件未开放 |
| `contact` | 调用 QQ 接口生成联系人/群推荐 Ark | 支持 | 只支持 qq 或 group 推荐卡片，不是任意 URL 分享 |
| `location` | 仅有硬编码占位实现 | 接受参数但实际不可用 | NapCat 丢弃经纬度、标题和内容，发送 text="测试", ext=""；接收端会显示不支持 |
| `onlinefile` | 转换器为空，并注明无需支持发送 | 不支持 | 应使用在线文件专用动作；插件当前也未开放这些动作 |
| `flashtransfer` | 转换器为空，并注明无需支持发送 | 不支持 | 应使用闪传专用动作；插件当前未开放 |
| `share（插件扩展）` | NapCat Schema 无原生 share 段 | 当前实现不可用 | 插件手工生成的 com.tencent.structmsg JSON 不被 QQ 客户端认可，会降级显示“发送者版本过低” |

## 明确不应等同为支持的项目

- NapCat 动作名称带有 `send_ark_share`，但当前实现实际返回联系人或群推荐 Ark 数据，不是任意 URL 分享卡片发送接口。
- `location` 虽存在 Schema 和转换器，但转换器是硬编码占位实现，不能算作可用的位置发送能力。
- `json` 是原始 Ark 透传能力，不会校验模板、补字段、注册 `app/view` 或提供签名。
- 插件契约文件中列出的 `can_send_image`、`can_send_record` 没有对应公开操作，不能仅因出现在契约文件中就标记为插件支持。
- NapCat 的测试、凭证、原始数据包、生命周期控制等动作即使已注册，也不代表适合暴露给模型；本表仍保留这些动作，以满足完整性核对。
- 修改机器人昵称的同时会更新个性签名，是 NapCat 接口原因。
