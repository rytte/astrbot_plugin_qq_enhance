from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationSpec:
    """Describe one explicitly supported OneBot operation.

    Args:
        tool: Model-visible tool name.
        operation: Operation enum value inside the tool.
        action: NapCat action name, or ``None`` for local orchestration.
        category: Feature pack name.
        risk: Risk level.
        permission: Minimum caller permission.
        contexts: Allowed conversation contexts.
        target_kind: Target scope used by permission checks.
        bot_role: Minimum QQ role required from the bot in a target group.
    """

    tool: str
    operation: str
    action: str | None
    category: str
    risk: str = "read"
    permission: str = "member"
    contexts: tuple[str, ...] = ("group", "private")
    target_kind: str = "none"
    bot_role: str = "member"

    @property
    def operation_id(self) -> str:
        """Return the globally unique operation identifier.

        Returns:
            Tool and operation joined with a dot.
        """

        return f"{self.tool}.{self.operation}"


def _op(
    tool: str,
    operation: str,
    action: str | None,
    category: str,
    *,
    risk: str = "read",
    permission: str = "member",
    contexts: tuple[str, ...] = ("group", "private"),
    target_kind: str = "none",
    bot_role: str = "member",
) -> OperationSpec:
    """Create a compact operation declaration.

    Args:
        tool: Model-visible tool name.
        operation: Operation enum value.
        action: NapCat action name.
        category: Feature pack name.
        risk: Risk level.
        permission: Minimum caller permission.
        contexts: Allowed contexts.
        target_kind: Target scope.
        bot_role: Required bot group role.

    Returns:
        Immutable operation specification.
    """

    return OperationSpec(
        tool,
        operation,
        action,
        category,
        risk,
        permission,
        contexts,
        target_kind,
        bot_role,
    )


OPERATIONS = (
    _op("qq_status", "login", "get_login_info", "status"),
    _op("qq_status", "runtime", "get_status", "status"),
    _op("qq_status", "version", "get_version_info", "status"),
    _op(
        "qq_status",
        "clients",
        "get_online_clients",
        "status",
        permission="astrbot_admin",
    ),
    _op("qq_status", "capabilities", None, "status"),
    _op(
        "qq_account_manage",
        "set_profile",
        "set_qq_profile",
        "account",
        risk="write",
        permission="astrbot_admin",
    ),
    _op(
        "qq_account_manage",
        "set_avatar",
        "set_qq_avatar",
        "account",
        risk="write",
        permission="astrbot_admin",
    ),
    _op(
        "qq_account_manage",
        "set_online_status",
        "set_online_status",
        "account",
        risk="write",
        permission="astrbot_admin",
    ),
    _op(
        "qq_user_info", "stranger", "get_stranger_info", "friend", target_kind="private"
    ),
    _op(
        "qq_user_info",
        "group_member",
        "get_group_member_info",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_friend_list",
        "friends",
        "get_friend_list",
        "friend",
        permission="astrbot_admin",
    ),
    _op(
        "qq_friend_list",
        "unidirectional",
        "get_unidirectional_friend_list",
        "friend",
        permission="astrbot_admin",
    ),
    _op(
        "qq_friend_history",
        "list",
        "get_friend_msg_history",
        "friend",
        target_kind="private",
    ),
    _op(
        "qq_friend_interact",
        "like",
        "send_like",
        "friend",
        risk="write",
        target_kind="private",
    ),
    _op(
        "qq_friend_interact",
        "poke",
        "friend_poke",
        "friend",
        risk="write",
        target_kind="private",
    ),
    _op("qq_friend_request", "list", None, "request", permission="astrbot_admin"),
    _op(
        "qq_friend_request",
        "approve",
        "set_friend_add_request",
        "request",
        risk="privileged",
        permission="astrbot_admin",
    ),
    _op(
        "qq_friend_request",
        "reject",
        "set_friend_add_request",
        "request",
        risk="privileged",
        permission="astrbot_admin",
    ),
    _op(
        "qq_friend_manage",
        "delete",
        "delete_friend",
        "friend",
        risk="destructive",
        permission="astrbot_admin",
        target_kind="private",
    ),
    _op(
        "qq_friend_manage",
        "set_remark",
        "set_friend_remark",
        "friend",
        risk="write",
        permission="astrbot_admin",
        target_kind="private",
    ),
    _op("qq_group_list", "list", "get_group_list", "group", permission="astrbot_admin"),
    _op("qq_group_info", "detail", "get_group_info", "group", target_kind="group"),
    _op(
        "qq_group_info", "detail_ex", "get_group_info_ex", "group", target_kind="group"
    ),
    _op("qq_group_info", "honor", "get_group_honor_info", "group", target_kind="group"),
    _op(
        "qq_group_info",
        "at_all_remain",
        "get_group_at_all_remain",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_group_info",
        "mute_list",
        "get_group_shut_list",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_group_members",
        "list",
        "get_group_member_list",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_group_members",
        "detail",
        "get_group_member_info",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_group_history",
        "list",
        "get_group_msg_history",
        "group",
        target_kind="group",
    ),
    _op(
        "qq_group_request",
        "list",
        "get_group_system_msg",
        "request",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_request",
        "ignored",
        "get_group_ignored_notifies",
        "request",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_request",
        "approve",
        "set_group_add_request",
        "request",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_request",
        "reject",
        "set_group_add_request",
        "request",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_member_manage",
        "poke",
        "group_poke",
        "group",
        risk="write",
        target_kind="group",
    ),
    _op(
        "qq_group_member_manage",
        "card",
        "set_group_card",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_member_manage",
        "title",
        "set_group_special_title",
        "group",
        risk="privileged",
        permission="group_owner",
        target_kind="group",
        bot_role="owner",
    ),
    _op(
        "qq_group_member_manage",
        "ban",
        "set_group_ban",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_member_manage",
        "kick",
        "set_group_kick",
        "group",
        risk="destructive",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_member_manage",
        "admin",
        "set_group_admin",
        "group",
        risk="destructive",
        permission="group_owner",
        target_kind="group",
        bot_role="owner",
    ),
    _op(
        "qq_group_manage",
        "whole_ban",
        "set_group_whole_ban",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_manage",
        "name",
        "set_group_name",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_manage",
        "avatar",
        "set_group_portrait",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_group_manage",
        "sign",
        "set_group_sign",
        "group",
        risk="write",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_manage",
        "leave",
        "set_group_leave",
        "group",
        risk="destructive",
        permission="astrbot_admin",
        target_kind="group",
    ),
    _op("qq_send_message", "send", None, "message", risk="write"),
    _op("qq_send_forward", "send", None, "message", risk="write"),
    _op("qq_message_get", "get", "get_msg", "message"),
    _op("qq_forward_get", "get", "get_forward_msg", "message"),
    _op(
        "qq_message_manage",
        "recall",
        "delete_msg",
        "message",
        risk="destructive",
    ),
    _op("qq_message_manage", "mark_read", "mark_msg_as_read", "message", risk="write"),
    _op(
        "qq_message_manage",
        "reaction_add",
        "set_msg_emoji_like",
        "message",
        risk="write",
    ),
    _op(
        "qq_message_manage",
        "reaction_remove",
        "set_msg_emoji_like",
        "message",
        risk="write",
    ),
    _op(
        "qq_recent_contacts",
        "list",
        "get_recent_contact",
        "message",
        permission="astrbot_admin",
    ),
    _op("qq_media", "get_image", "get_image", "media"),
    _op("qq_media", "get_record", "get_record", "media"),
    _op("qq_media", "convert_record", "get_record", "media", risk="write"),
    _op("qq_media", "ocr", "ocr_image", "media", risk="write"),
    _op(
        "qq_group_files",
        "info",
        "get_group_file_system_info",
        "file",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "list_root",
        "get_group_root_files",
        "file",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "list_folder",
        "get_group_files_by_folder",
        "file",
        target_kind="group",
    ),
    _op("qq_group_files", "url", "get_group_file_url", "file", target_kind="group"),
    _op(
        "qq_group_files",
        "upload",
        "upload_group_file",
        "file",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "mkdir",
        "create_group_file_folder",
        "file",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "delete",
        "delete_group_file",
        "file",
        risk="destructive",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "rmdir",
        "delete_group_folder",
        "file",
        risk="destructive",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "move",
        "move_group_file",
        "file",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "rename",
        "rename_group_file",
        "file",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
    ),
    _op(
        "qq_group_files",
        "transfer",
        "trans_group_file",
        "file",
        risk="privileged",
        permission="astrbot_admin",
        target_kind="group",
    ),
    _op(
        "qq_private_files",
        "url",
        "get_private_file_url",
        "file",
        permission="astrbot_admin",
        target_kind="private",
    ),
    _op(
        "qq_private_files",
        "upload",
        "upload_private_file",
        "file",
        risk="write",
        permission="astrbot_admin",
        target_kind="private",
    ),
    _op("qq_essence", "list", "get_essence_msg_list", "group", target_kind="group"),
    _op(
        "qq_essence",
        "add",
        "set_essence_msg",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_essence",
        "remove",
        "delete_essence_msg",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op("qq_notice", "list", "_get_group_notice", "group", target_kind="group"),
    _op("qq_notice", "detail", "_get_group_notice", "group", target_kind="group"),
    _op(
        "qq_notice",
        "send",
        "_send_group_notice",
        "group",
        risk="privileged",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
    _op(
        "qq_notice",
        "delete",
        "_del_group_notice",
        "group",
        risk="destructive",
        permission="group_admin",
        target_kind="group",
        bot_role="admin",
    ),
)


OPERATION_MAP = {item.operation_id: item for item in OPERATIONS}
TOOL_OPERATIONS: dict[str, tuple[str, ...]] = {}
for _item in OPERATIONS:
    TOOL_OPERATIONS.setdefault(_item.tool, ())
    TOOL_OPERATIONS[_item.tool] += (_item.operation,)

if len(OPERATION_MAP) != len(OPERATIONS):
    raise RuntimeError("Duplicate QQ operation ID in capability catalog")


@dataclass(frozen=True, slots=True)
class ParameterRule:
    """Declare exact accepted parameters for one operation.

    Args:
        required: Parameters that must be present and non-empty.
        optional: Additional parameters accepted by the operation.
        hint: Compact structural guidance for nested parameters.
    """

    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    hint: str = ""

    @property
    def allowed(self) -> frozenset[str]:
        """Return all accepted parameter names.

        Returns:
            Immutable accepted parameter set.
        """

        return frozenset((*self.required, *self.optional))


def _params(
    *required: str, optional: tuple[str, ...] = (), hint: str = ""
) -> ParameterRule:
    """Create a compact parameter rule used throughout the catalog.

    Args:
        *required: Required parameter names.
        optional: Optional parameter names.
        hint: Compact structural guidance for nested parameters.

    Returns:
        Immutable parameter rule.
    """

    return ParameterRule(required, optional, hint)


PAGE_PARAMS = ("cursor", "page_size")
OPERATION_PARAMETERS = {
    "qq_status.login": _params(),
    "qq_status.runtime": _params(),
    "qq_status.version": _params(),
    "qq_status.clients": _params(optional=("no_cache",)),
    "qq_status.capabilities": _params(optional=PAGE_PARAMS),
    "qq_account_manage.set_profile": _params(
        "nickname", optional=("personal_note", "company", "email", "college")
    ),
    "qq_account_manage.set_avatar": _params(
        optional=("path", "url", "base64", "media_ref")
    ),
    "qq_account_manage.set_online_status": _params(
        "status",
        optional=("ext_status", "battery_status"),
        hint=(
            "status 支持 online、qme、leave、busy、dont_disturb、invisible、"
            "listening、weather、meet_spring 或对应 NapCat 基础状态码。"
        ),
    ),
    "qq_user_info.stranger": _params("user_id", optional=("no_cache",)),
    "qq_user_info.group_member": _params("group_id", "user_id", optional=("no_cache",)),
    "qq_friend_list.friends": _params(optional=(*PAGE_PARAMS, "no_cache")),
    "qq_friend_list.unidirectional": _params(optional=PAGE_PARAMS),
    "qq_friend_history.list": _params(
        "user_id", optional=("message_seq", "count", *PAGE_PARAMS)
    ),
    "qq_friend_interact.like": _params("user_id", optional=("times",)),
    "qq_friend_interact.poke": _params("user_id"),
    "qq_friend_request.list": _params(optional=("status", *PAGE_PARAMS)),
    "qq_friend_request.approve": _params(
        optional=("request_id", "flag", "remark"),
        hint="使用通知中的 request_id，或直接提供 flag；request_id 与 flag 必须二选一。",
    ),
    "qq_friend_request.reject": _params(
        optional=("request_id", "flag"),
        hint="使用通知中的 request_id，或直接提供 flag；request_id 与 flag 必须二选一。",
    ),
    "qq_friend_manage.delete": _params("user_id"),
    "qq_friend_manage.set_remark": _params("user_id", "remark"),
    "qq_group_list.list": _params(optional=(*PAGE_PARAMS, "no_cache")),
    "qq_group_info.detail": _params("group_id", optional=("no_cache",)),
    "qq_group_info.detail_ex": _params("group_id"),
    "qq_group_info.honor": _params("group_id", optional=("honor_type",)),
    "qq_group_info.at_all_remain": _params("group_id"),
    "qq_group_info.mute_list": _params("group_id", optional=PAGE_PARAMS),
    "qq_group_members.list": _params("group_id", optional=("no_cache", *PAGE_PARAMS)),
    "qq_group_members.detail": _params("group_id", "user_id", optional=("no_cache",)),
    "qq_group_history.list": _params(
        "group_id", optional=("message_seq", "count", *PAGE_PARAMS)
    ),
    "qq_group_request.list": _params(optional=("group_id",)),
    "qq_group_request.ignored": _params("group_id", optional=PAGE_PARAMS),
    "qq_group_request.approve": _params(
        optional=("request_id", "group_id", "flag", "sub_type"),
        hint=(
            "优先使用通知中的 request_id；否则必须同时提供 group_id、flag、sub_type。"
            "两种形式不能混用。"
        ),
    ),
    "qq_group_request.reject": _params(
        optional=("request_id", "group_id", "flag", "sub_type", "reason"),
        hint=(
            "优先使用通知中的 request_id；否则必须同时提供 group_id、flag、sub_type。"
            "两种形式不能混用。"
        ),
    ),
    "qq_group_member_manage.poke": _params("group_id", "user_id"),
    "qq_group_member_manage.card": _params("group_id", "user_id", "card"),
    "qq_group_member_manage.title": _params(
        "group_id", "user_id", "special_title", optional=("duration",)
    ),
    "qq_group_member_manage.ban": _params(
        "group_id", "user_id", optional=("duration",)
    ),
    "qq_group_member_manage.kick": _params(
        "group_id", "user_id", optional=("reject_add_request",)
    ),
    "qq_group_member_manage.admin": _params("group_id", "user_id", "enable"),
    "qq_group_manage.whole_ban": _params("group_id", "enable"),
    "qq_group_manage.name": _params("group_id", "group_name"),
    "qq_group_manage.avatar": _params(
        "group_id", optional=("path", "url", "base64", "media_ref", "cache")
    ),
    "qq_group_manage.sign": _params("group_id"),
    "qq_group_manage.leave": _params("group_id", optional=("is_dismiss",)),
    "qq_send_message.send": _params(
        "target",
        "components",
        hint=(
            'target 优先使用 {"type":"current"}；跨会话使用 '
            '{"type":"group","id":正整数} 或 {"type":"private","id":正整数}。'
            "组件字段必须直接放在对象中，"
            '不得使用 data 包装。常用组件：{"type":"text","text":"..."}、'
            '{"type":"face","id":14}、{"type":"at","id":正整数}、'
            '{"type":"reply","id":正整数}、{"type":"dice"}、{"type":"rps"}、'
            '{"type":"share","url":"跳转地址","title":"标题",'
            '"content":"可选内容","image":"可选预览图"}。分享卡片会安全编码为 Ark JSON，'
            "必须作为唯一组件发送；不要自行拼接分享卡片 JSON，也不得擅自替换用户提供的 URL。"
            "媒体组件 type 必须是 image、record、video 或 file，并提供 path、url、"
            "base64、media_ref 中恰好一项。用户按歌名点歌时必须使用 "
            '{"type":"music","music_type":"qq_search","query":"准确歌名",'
            '"artist":"可选歌手"}，插件会查询并校验 QQ 音乐结果；不得凭记忆猜歌曲 ID。'
            "只有平台 ID 明确出现在用户当前消息中时才可使用平台 ID 卡片 "
            '{"type":"music","music_type":"qq","id":"歌曲ID"}，平台支持 '
            "qq、163、kugou、kuwo、migu；该模式依赖 NapCat 的 musicSignUrl "
            "支持 ID 解析。签名服务不支持 ID 时，使用 "
            '{"type":"music","music_type":"custom","url":"跳转地址",'
            '"image":"封面地址","audio":"可选音频地址","title":"可选标题",'
            '"content":"可选简介"}。不要先发送测试或占位消息。'
            "音乐卡片必须作为唯一组件单独发送；如需附带说明文字，请在最终回复中简短说明。"
            "调用成功仅表示 NapCat 已接受发送请求，最终回复不得重复其中的正文或卡片。"
        ),
    ),
    "qq_send_forward.send": _params(
        "target",
        "nodes",
        hint=(
            'target 优先使用 {"type":"current"}。转发现有消息时，nodes 中每项'
            '使用 {"message_id":正整数}；自定义节点使用 '
            '{"sender_id":正整数,"sender_name":"名称","components":['
            '{"type":"text","text":"内容"}]}。节点字段直接放在对象中，'
            "不得使用 type、data、name、uin 或 content 包装。"
        ),
    ),
    "qq_message_get.get": _params("message_id"),
    "qq_forward_get.get": _params(
        optional=("message_id", "res_id", "depth"),
        hint=(
            "message_id 与 res_id 必须且只能提供一项。读取刚发送的合并转发时，"
            "优先使用 qq_send_forward 返回的数字 message_id；NapCat 使用 res_id "
            "读取私聊转发时可能规范化自定义发送者信息。"
        ),
    ),
    "qq_message_manage.recall": _params("message_id"),
    "qq_message_manage.mark_read": _params("message_id"),
    "qq_message_manage.reaction_add": _params("message_id", "emoji_id"),
    "qq_message_manage.reaction_remove": _params("message_id", "emoji_id"),
    "qq_recent_contacts.list": _params(optional=("count", *PAGE_PARAMS)),
    "qq_media.get_image": _params("file"),
    "qq_media.get_record": _params("file", optional=("out_format",)),
    "qq_media.convert_record": _params("file", "out_format"),
    "qq_media.ocr": _params(
        optional=("path", "url", "base64", "media_ref", *PAGE_PARAMS)
    ),
    "qq_group_files.info": _params("group_id"),
    "qq_group_files.list_root": _params("group_id", optional=PAGE_PARAMS),
    "qq_group_files.list_folder": _params(
        "group_id", "folder_id", optional=PAGE_PARAMS
    ),
    "qq_group_files.url": _params("group_id", "file_id", "busid"),
    "qq_group_files.upload": _params(
        "group_id", optional=("path", "url", "base64", "media_ref", "name", "folder")
    ),
    "qq_group_files.mkdir": _params("group_id", "name", optional=("parent_id",)),
    "qq_group_files.delete": _params("group_id", "file_id", "busid"),
    "qq_group_files.rmdir": _params("group_id", "folder_id"),
    "qq_group_files.move": _params(
        "group_id", "file_id", "current_parent_directory", "target_parent_directory"
    ),
    "qq_group_files.rename": _params(
        "group_id", "file_id", "current_parent_directory", "new_name"
    ),
    "qq_group_files.transfer": _params("group_id", "file_id"),
    "qq_private_files.url": _params(
        optional=("user_id", "file_id"),
        hint="不传 file_id 时返回当前私聊附件已有的 QQ 下载地址。",
    ),
    "qq_private_files.upload": _params(
        "user_id", optional=("path", "url", "base64", "media_ref", "name")
    ),
    "qq_essence.list": _params("group_id", optional=PAGE_PARAMS),
    "qq_essence.add": _params("group_id", "message_id"),
    "qq_essence.remove": _params("group_id", "message_id"),
    "qq_notice.list": _params("group_id", optional=PAGE_PARAMS),
    "qq_notice.detail": _params("group_id", "notice_id"),
    "qq_notice.send": _params("group_id", "content", optional=("title", "image")),
    "qq_notice.delete": _params("group_id", "notice_id"),
}

if set(OPERATION_PARAMETERS) != set(OPERATION_MAP):
    missing = sorted(set(OPERATION_MAP) - set(OPERATION_PARAMETERS))
    extra = sorted(set(OPERATION_PARAMETERS) - set(OPERATION_MAP))
    raise RuntimeError(f"Invalid parameter catalog, missing={missing}, extra={extra}")


TOOL_DESCRIPTIONS = {
    "qq_status": "查询 QQ 登录、运行、版本、客户端与消息能力。",
    "qq_account_manage": "修改机器人公开资料、头像或在线状态。",
    "qq_user_info": "查询陌生人或群成员公开资料；查询非好友仅限管理员私聊。",
    "qq_friend_list": "查询好友或单向好友列表。",
    "qq_friend_history": "分页查询好友私聊历史。",
    "qq_friend_interact": "向好友点赞或戳一戳。",
    "qq_friend_request": "查询、通过或拒绝好友申请。",
    "qq_friend_manage": "删除好友或修改好友备注。",
    "qq_group_list": "查询机器人加入的群列表。",
    "qq_group_info": "查询群详情、荣誉、@全体次数或禁言列表。",
    "qq_group_members": "查询群成员列表或成员详情。",
    "qq_group_history": "分页查询群聊历史。",
    "qq_group_request": "查询、通过或拒绝加群申请和群邀请；管理员私聊可查询全部群申请。",
    "qq_group_member_manage": "戳一戳群成员，或修改群成员名片、头衔、禁言、移出和管理员身份。",
    "qq_group_manage": "执行全员禁言、改群名或头像、签到、退群。",
    "qq_send_message": (
        "向当前或获授权的 QQ 会话发送结构化消息；音乐卡片必须作为唯一组件单独发送。"
        "发送猜拳或骰子后会自动回查并返回最终随机结果。"
        "调用成功仅表示 NapCat 已接受发送请求；不要在最终回复中重复消息正文或卡片。"
    ),
    "qq_send_forward": "发送群聊或私聊合并转发。",
    "qq_message_get": "根据消息 ID 获取并规范化消息。",
    "qq_forward_get": "读取并展开合并转发消息。",
    "qq_message_manage": "撤回、标记已读或增删消息表情回应。",
    "qq_recent_contacts": "查询最近联系人和消息摘要。",
    "qq_media": "获取图片或语音、转码语音、执行图片 OCR。",
    "qq_group_files": "查询或管理群文件与文件夹。",
    "qq_private_files": "获取私聊文件链接或上传私聊文件。",
    "qq_essence": "查询、添加或移除群精华消息。",
    "qq_notice": "查询、发布或删除群公告。",
}


KEYWORD_TOOLS = {
    "文件": {"qq_group_files", "qq_private_files"},
    "图片": {"qq_media", "qq_send_message"},
    "语音": {"qq_media", "qq_send_message"},
    "OCR": {"qq_media"},
    "ocr": {"qq_media"},
    "转发": {"qq_send_forward", "qq_forward_get"},
    "合并": {"qq_send_forward", "qq_forward_get"},
    "公告": {"qq_notice"},
    "精华": {"qq_essence"},
    "申请": {"qq_friend_request", "qq_group_request"},
    "邀请": {"qq_group_request"},
    "好友": {
        "qq_friend_list",
        "qq_friend_history",
        "qq_friend_interact",
        "qq_friend_manage",
    },
    "群员": {"qq_group_members", "qq_group_member_manage"},
    "群成员": {"qq_group_members", "qq_group_member_manage"},
    "群昵称": {"qq_group_member_manage"},
    "群名片": {"qq_group_member_manage"},
    "成员名片": {"qq_group_member_manage"},
    "群名称": {"qq_group_manage"},
    "修改群名": {"qq_group_manage"},
    "改群名": {"qq_group_manage"},
    "禁言": {"qq_group_member_manage", "qq_group_manage"},
    "踢": {"qq_group_member_manage"},
    "移除": {"qq_group_member_manage"},
    "移出": {"qq_group_member_manage"},
    "踢出": {"qq_group_member_manage"},
    "管理员": {"qq_group_member_manage"},
    "签到": {"qq_group_manage"},
    "退出群": {"qq_group_manage"},
    "退群": {"qq_group_manage"},
    "群聊": {
        "qq_group_list",
        "qq_group_info",
        "qq_group_members",
        "qq_group_history",
    },
    "历史": {"qq_group_history", "qq_friend_history"},
    "消息": {"qq_send_message", "qq_message_get", "qq_message_manage"},
    "表情": {"qq_send_message", "qq_message_manage"},
    "戳": {"qq_friend_interact", "qq_group_member_manage"},
    "点赞": {"qq_friend_interact", "qq_message_manage"},
    "状态": {"qq_status", "qq_account_manage"},
    "头像": {"qq_account_manage", "qq_group_manage", "qq_media"},
    "昵称": {"qq_account_manage"},
    "备注": {"qq_friend_manage"},
}


NAPCAT_CONTRACT_VERSION = "4.18.19"
NAPCAT_MIN_VERSION = (4, 18, 19)
NAPCAT_MAX_VERSION = (5, 0, 0)
