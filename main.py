from __future__ import annotations

import asyncio
import hashlib
import json
import time
from contextlib import suppress
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import (
    get_astrbot_config_path,
    get_astrbot_plugin_data_path,
)

from .catalog import (
    KEYWORD_TOOLS,
    OPERATION_MAP,
    OPERATION_PARAMETERS,
    TOOL_DESCRIPTIONS,
    TOOL_OPERATIONS,
)
from .inbound import describe_inbound_event, is_red_packet_event
from .runtime import QQRuntime, validate_config
from .storage import Storage


def _format_audit_rows(rows: list[dict]) -> str:
    """Format metadata-only audit rows for QQ chat output.

    Args:
        rows: Audit records ordered from newest to oldest.

    Returns:
        Human-readable audit text without sensitive parameters.
    """

    if not rows:
        return "暂无审计记录。"
    risk_labels = {
        "read": "读取",
        "write": "写入",
        "privileged": "高权限",
        "destructive": "破坏性",
    }
    decision_labels = {
        "allowed": "已放行",
        "confirmation_required": "待确认",
        "confirmed": "已确认",
        "denied": "已拒绝",
        "failed": "失败",
    }
    result_labels = {
        "ok": "成功",
        "started": "开始执行",
        "confirmation_required": "等待确认",
        "permission_denied": "权限不足",
        "invalid_parameters": "参数无效",
        "target_not_found": "目标不存在",
        "capability_unavailable": "能力不可用",
        "protocol_rejected": "QQ 协议拒绝",
        "network_error": "网络错误",
        "timeout": "超时",
        "response_invalid": "响应无效",
        "internal_error": "内部错误",
    }
    entries = []
    for index, row in enumerate(rows, 1):
        target_kind = {
            "group": "群",
            "private": "私聊用户",
            "none": "无",
        }.get(row["target_kind"], row["target_kind"])
        target = (
            f"{target_kind} {row['target_id']}" if row["target_id"] else target_kind
        )
        risk = row["risk"]
        decision = row["decision"]
        result_code = row["result_code"]
        lines = [
            f"{index}. {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['created_at']))}",
            f"   操作：{row['operation_id']}",
            f"   调用者：{row['caller_id']}",
            f"   目标：{target}",
            f"   风险：{risk_labels.get(risk, risk)}（{risk}）",
            f"   决策：{decision_labels.get(decision, decision)}（{decision}）",
            f"   结果：{result_labels.get(result_code, result_code)}（{result_code}）",
            f"   耗时：{row['duration_ms']} ms",
        ]
        if row["pending_id"]:
            lines.append(f"   确认 ID：{row['pending_id']}")
        entries.append("\n".join(lines))
    return f"最近 {len(rows)} 条审计记录：\n\n" + "\n\n".join(entries)


_persisted_config_path = (
    Path(get_astrbot_config_path())
    / f"{Path(__file__).resolve().parent.name}_config.json"
)
if _persisted_config_path.is_file():
    try:
        _persisted_config = json.loads(
            _persisted_config_path.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("QQ 扩展工具配置文件无法读取或不是有效 JSON") from exc
    validate_config(_persisted_config)


class QQExtensionToolsPlugin(Star):
    """Expose bounded QQ tools and inbound semantics to AstrBot models."""

    def __init__(
        self, context: Context, config: AstrBotConfig | dict | None = None
    ) -> None:
        super().__init__(context)
        self.config = validate_config(dict(config or {}))
        data_dir = (
            Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_qq_extension_tools"
        )
        self.storage = Storage(data_dir / "qq_extension_tools.sqlite3")
        self.runtime = QQRuntime(context, self.config, self.storage)
        self.cleanup_task: asyncio.Task[None] | None = None

    async def initialize(self) -> None:
        """Initialize persistence, tool schemas, and lifecycle cleanup."""

        await self.storage.initialize()
        for tool_name, operations in TOOL_OPERATIONS.items():
            tool = self.context.provider_manager.llm_tools.get_func(tool_name)
            if tool is None:
                raise RuntimeError(f"QQ tool registration missing: {tool_name}")
            enabled_operations = [
                operation
                for operation in operations
                if self.runtime.operation_enabled(f"{tool_name}.{operation}")
            ]
            if not enabled_operations:
                tool.active = False
                continue
            details = []
            for operation in enabled_operations:
                rule = OPERATION_PARAMETERS[f"{tool_name}.{operation}"]
                required = "、".join(rule.required) or "无"
                optional = "、".join(rule.optional) or "无"
                detail = f"{operation}: 必填[{required}]，可选[{optional}]"
                if rule.hint:
                    detail += f"。{rule.hint}"
                details.append(detail)
            tool.description = TOOL_DESCRIPTIONS[tool_name]
            tool.parameters = {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": enabled_operations,
                        "description": "要执行的资源操作。",
                    },
                    "params": {
                        "type": "object",
                        "description": "；".join(details),
                    },
                },
                "required": ["operation", "params"],
                "additionalProperties": False,
            }
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("QQ extension tools initialized")

    async def _cleanup_loop(self) -> None:
        """Run periodic retention cleanup until plugin termination."""

        while True:
            try:
                await self.runtime.cleanup()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("QQ extension tools cleanup failed")
            await asyncio.sleep(self.config["files"]["cleanup_interval_seconds"])

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def enrich_inbound_qq_components(self, event: AstrMessageEvent) -> None:
        """Append bounded semantics for NapCat components ignored by AstrBot.

        Args:
            event: Current message or notice event.
        """

        if event.get_platform_name() != "aiocqhttp":
            return
        platform_id = self.config["platform"]["platform_id"]
        if platform_id and event.get_platform_id() != platform_id:
            return
        inbound = self.config["inbound"]
        raw = getattr(event.message_obj, "raw_message", None)
        semantics = describe_inbound_event(
            raw,
            str(event.get_self_id() or ""),
            semanticize_components=inbound["semanticize_components"],
            respond_to_poke=inbound["respond_to_poke"],
            max_components=self.config["limits"]["max_components"],
            max_chars=inbound["max_semantic_chars"],
        )
        if not semantics:
            return
        current = str(event.message_str or "").strip()
        enriched = f"{current}\n{semantics}" if current else semantics
        event.message_str = enriched
        event.message_obj.message_str = enriched
        targeted_poke = (
            isinstance(raw, dict)
            and raw.get("post_type") == "notice"
            and raw.get("notice_type") == "notify"
            and raw.get("sub_type") == "poke"
        )
        red_packet = inbound["respond_to_red_packet"] and is_red_packet_event(
            raw, self.config["limits"]["max_components"]
        )
        if targeted_poke or red_packet:
            event.is_wake = True
            event.is_at_or_wake_command = True

    @filter.on_llm_request()
    async def select_tools(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """Prune only the current request's QQ tool set.

        Args:
            event: Current message event.
            request: Current provider request with a request-local tool set.
        """

        if request.func_tool is None:
            return
        qq_tools = set(TOOL_OPERATIONS)
        if event.get_platform_name() != "aiocqhttp":
            for tool_name in qq_tools:
                request.func_tool.remove_tool(tool_name)
            return

        is_admin = event.is_admin()
        current_group = str(event.get_group_id() or "")
        raw = getattr(event.message_obj, "raw_message", {})
        raw_sender = raw.get("sender", {}) if isinstance(raw, dict) else {}
        qq_role = str(raw_sender.get("role", "member"))
        visible = set()
        for tool_name, operations in TOOL_OPERATIONS.items():
            for operation in operations:
                operation_id = f"{tool_name}.{operation}"
                if not self.runtime.operation_enabled(operation_id):
                    continue
                spec = OPERATION_MAP[operation_id]
                if spec.permission == "astrbot_admin" and not is_admin:
                    continue
                if spec.permission == "group_admin" and not is_admin:
                    if not current_group or qq_role not in {"admin", "owner"}:
                        continue
                    if (
                        qq_role == "admin"
                        and not self.config["permissions"]["allow_group_admin"]
                    ):
                        continue
                    if (
                        qq_role == "owner"
                        and not self.config["permissions"]["allow_group_owner"]
                    ):
                        continue
                if spec.permission == "group_owner" and not is_admin:
                    if (
                        not current_group
                        or qq_role != "owner"
                        or not self.config["permissions"]["allow_group_owner"]
                    ):
                        continue
                if current_group and spec.target_kind == "private":
                    continue
                if not current_group and spec.target_kind == "group":
                    if not (
                        is_admin
                        and (
                            self.config["permissions"]["allow_cross_group"]
                            or operation_id == "qq_group_request.list"
                        )
                    ):
                        continue
                visible.add(tool_name)
                break

        prompt = request.prompt or event.message_str or ""
        if len(prompt.strip()) <= 16 and not any(
            keyword in prompt for keyword in KEYWORD_TOOLS
        ):
            # Short follow-ups need the immediately preceding user intent for routing.
            for context_item in reversed(request.contexts):
                if (
                    not isinstance(context_item, dict)
                    or context_item.get("role") != "user"
                ):
                    continue
                content = context_item.get("content", "")
                if isinstance(content, str):
                    previous_prompt = content
                elif isinstance(content, list):
                    previous_prompt = "".join(
                        str(part.get("text", ""))
                        for part in content
                        if isinstance(part, dict)
                        and part.get("type") in {"text", "input_text"}
                    )
                else:
                    previous_prompt = ""
                if (
                    previous_prompt.strip()
                    and previous_prompt.strip() != prompt.strip()
                    and any(keyword in previous_prompt for keyword in KEYWORD_TOOLS)
                ):
                    prompt = f"{previous_prompt}\n{prompt}"
                    break
        requested = set()
        for keyword, tool_names in KEYWORD_TOOLS.items():
            if keyword in prompt:
                requested.update(tool_names)
        message_components = getattr(event.message_obj, "message", [])
        if not current_group and any(
            isinstance(component, File) for component in message_components
        ):
            requested.add("qq_private_files")
        mode = self.config["toolsets"]["exposure_mode"]
        if mode != "full":
            if current_group:
                selected = {
                    "qq_status",
                    "qq_group_info",
                    "qq_group_members",
                    "qq_group_history",
                    "qq_send_message",
                    "qq_message_get",
                    "qq_message_manage",
                    "qq_media",
                }
            else:
                selected = {
                    "qq_status",
                    "qq_user_info",
                    "qq_friend_history",
                    "qq_friend_interact",
                    "qq_send_message",
                    "qq_message_get",
                    "qq_message_manage",
                    "qq_media",
                }
            if mode == "balanced":
                selected.update(requested)
                if is_admin:
                    selected.update(
                        {
                            "qq_friend_list" if not current_group else "qq_group_list",
                            "qq_recent_contacts",
                        }
                    )
                    if not current_group:
                        selected.add("qq_friend_request")
                maximum = 15
            else:
                selected.update(requested)
                maximum = 10
            ordered = sorted(
                selected & visible,
                key=lambda name: (name not in requested, name),
            )
            visible &= set(ordered[:maximum])
        visible &= self.runtime.enabled_tools()
        for tool_name in qq_tools - visible:
            request.func_tool.remove_tool(tool_name)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def capture_onebot_event(self, event: AstrMessageEvent) -> None:
        """Persist normalized OneBot requests and notices without triggering LLM.

        Args:
            event: Incoming adapter event.
        """

        if event.get_platform_name() != "aiocqhttp":
            return
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict) or raw.get("post_type") not in {
            "request",
            "notice",
        }:
            return
        post_type = str(raw["post_type"])
        event_type = str(
            raw.get("request_type")
            if post_type == "request"
            else raw.get("notice_type") or ""
        )
        event_name = f"{post_type}.{event_type}"
        enabled = self.config["events"]["enabled_types"]
        if enabled and event_type not in enabled and event_name not in enabled:
            return
        actor_id = str(raw.get("user_id") or raw.get("operator_id") or "")
        group_id = str(raw.get("group_id") or "")
        sub_type = str(raw.get("sub_type") or "")
        flag = str(raw.get("flag") or "")
        safe_data = {
            key: raw[key]
            for key in (
                "target_id",
                "operator_id",
                "message_id",
                "file_id",
                "duration",
                "honor_type",
                "role",
            )
            if key in raw
        }
        event_key = hashlib.sha256(
            json.dumps(
                [
                    event.get_platform_id(),
                    post_type,
                    event_type,
                    sub_type,
                    flag,
                    raw.get("time"),
                ],
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()
        comment = str(raw.get("comment") or "")
        await self.storage.add_event(
            {
                "created_at": int(raw.get("time") or time.time()),
                "platform_id": event.get_platform_id(),
                "post_type": post_type,
                "event_type": event_type,
                "sub_type": sub_type,
                "actor_id": actor_id,
                "group_id": group_id,
                "event_key": event_key,
                "data": safe_data,
                "flag": flag,
                "comment_hash": hashlib.sha256(comment.encode()).hexdigest()
                if comment
                else "",
            }
        )

    @filter.command("qq")
    async def qq_command(
        self, event: AstrMessageEvent, action: str = "", value: str = ""
    ) -> None:
        """Manage QQ confirmations and metadata-only audits.

        Args:
            action: confirm, cancel, pending, audit, or help.
            value: Pending identifier or audit result count.
        """

        action = action.strip().lower()
        if action == "confirm":
            text = await self.runtime.confirm(event, value.strip().lower())
        elif action == "cancel":
            cancelled = await self.storage.cancel_pending(
                value.strip().lower(),
                str(event.get_sender_id() or ""),
                str(event.unified_msg_origin),
                event.get_platform_id(),
            )
            text = "已取消待确认操作。" if cancelled else "未找到可取消的待确认操作。"
        elif action == "pending":
            rows = await self.storage.list_pending(
                str(event.get_sender_id() or ""),
                str(event.unified_msg_origin),
                event.get_platform_id(),
            )
            if rows:
                text = "待确认操作：\n" + "\n".join(
                    f"- {row['pending_id']} {row['summary']}（剩余约 "
                    f"{max(0, row['expires_at'] - int(time.time()))} 秒）"
                    for row in rows
                )
            else:
                text = "当前会话没有待确认操作。"
        elif action == "audit":
            if not event.is_admin():
                text = "仅 AstrBot 管理员可以查询审计记录。"
            else:
                try:
                    limit = int(value or 20)
                except ValueError:
                    limit = 0
                if not 1 <= limit <= 100:
                    text = "审计条数必须是 1～100 的整数。"
                else:
                    rows = await self.storage.list_audit(limit)
                    text = _format_audit_rows(rows)
        else:
            text = (
                "QQ 扩展工具命令：\n"
                "/qq confirm <id>\n/qq cancel <id>\n"
                "/qq pending\n/qq audit [1-100]"
            )
        yield event.plain_result(text)

    @filter.llm_tool(name="qq_status")
    async def qq_status(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询 QQ 账号与协议状态。

        Args:
            operation(string): login、runtime、version、clients 或 capabilities。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_status", operation, params)

    @filter.llm_tool(name="qq_account_manage")
    async def qq_account_manage(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """管理机器人 QQ 账号公开资料。

        Args:
            operation(string): set_profile、set_avatar 或 set_online_status。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_account_manage", operation, params)

    @filter.llm_tool(name="qq_user_info")
    async def qq_user_info(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询 QQ 用户公开资料。

        Args:
            operation(string): stranger 或 group_member。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_user_info", operation, params)

    @filter.llm_tool(name="qq_friend_list")
    async def qq_friend_list(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询好友列表。

        Args:
            operation(string): friends 或 unidirectional。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_friend_list", operation, params)

    @filter.llm_tool(name="qq_friend_history")
    async def qq_friend_history(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询好友消息历史。

        Args:
            operation(string): list。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_friend_history", operation, params)

    @filter.llm_tool(name="qq_friend_interact")
    async def qq_friend_interact(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """对好友执行点赞或戳一戳。

        Args:
            operation(string): like 或 poke。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(
            event, "qq_friend_interact", operation, params
        )

    @filter.llm_tool(name="qq_friend_request")
    async def qq_friend_request(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询或处理好友申请。

        Args:
            operation(string): list、approve 或 reject。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_friend_request", operation, params)

    @filter.llm_tool(name="qq_friend_manage")
    async def qq_friend_manage(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """管理好友关系与备注。

        Args:
            operation(string): delete 或 set_remark。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_friend_manage", operation, params)

    @filter.llm_tool(name="qq_group_list")
    async def qq_group_list(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询机器人群列表。

        Args:
            operation(string): list。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_list", operation, params)

    @filter.llm_tool(name="qq_group_info")
    async def qq_group_info(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询群资料和状态。

        Args:
            operation(string): detail、detail_ex、honor、at_all_remain 或 mute_list。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_info", operation, params)

    @filter.llm_tool(name="qq_group_members")
    async def qq_group_members(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询群成员。

        Args:
            operation(string): list 或 detail。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_members", operation, params)

    @filter.llm_tool(name="qq_group_history")
    async def qq_group_history(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询群消息历史。

        Args:
            operation(string): list。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_history", operation, params)

    @filter.llm_tool(name="qq_group_request")
    async def qq_group_request(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询或处理加群申请与邀请。

        Args:
            operation(string): list、ignored、approve 或 reject。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_request", operation, params)

    @filter.llm_tool(name="qq_group_member_manage")
    async def qq_group_member_manage(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """与群成员互动或管理群成员权限和状态。

        Args:
            operation(string): poke、card、title、ban、kick 或 admin。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(
            event, "qq_group_member_manage", operation, params
        )

    @filter.llm_tool(name="qq_group_manage")
    async def qq_group_manage(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """管理群资料和全局状态。

        Args:
            operation(string): whole_ban、name、avatar、sign 或 leave。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_manage", operation, params)

    @filter.llm_tool(name="qq_send_message")
    async def qq_send_message(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """发送显式结构化 QQ 消息。

        Args:
            operation(string): send。
            params(object): 包含 target 和 components 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_send_message", operation, params)

    @filter.llm_tool(name="qq_send_forward")
    async def qq_send_forward(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """发送群聊或私聊合并转发。

        Args:
            operation(string): send。
            params(object): 包含 target 和 nodes 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_send_forward", operation, params)

    @filter.llm_tool(name="qq_message_get")
    async def qq_message_get(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """获取指定 QQ 消息。

        Args:
            operation(string): get。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_message_get", operation, params)

    @filter.llm_tool(name="qq_forward_get")
    async def qq_forward_get(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """读取合并转发消息。

        Args:
            operation(string): get。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_forward_get", operation, params)

    @filter.llm_tool(name="qq_message_manage")
    async def qq_message_manage(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """撤回、已读或管理消息表情回应。

        Args:
            operation(string): recall、mark_read、reaction_add 或 reaction_remove。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_message_manage", operation, params)

    @filter.llm_tool(name="qq_recent_contacts")
    async def qq_recent_contacts(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询最近联系人。

        Args:
            operation(string): list。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(
            event, "qq_recent_contacts", operation, params
        )

    @filter.llm_tool(name="qq_media")
    async def qq_media(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """读取、转换或识别 QQ 媒体。

        Args:
            operation(string): get_image、get_record、convert_record 或 ocr。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_media", operation, params)

    @filter.llm_tool(name="qq_group_files")
    async def qq_group_files(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询或管理群文件。

        Args:
            operation(string): info、list_root、list_folder、url、upload、mkdir、delete、rmdir、move、rename 或 transfer。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_group_files", operation, params)

    @filter.llm_tool(name="qq_private_files")
    async def qq_private_files(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询或上传私聊文件。

        Args:
            operation(string): url 或 upload。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_private_files", operation, params)

    @filter.llm_tool(name="qq_essence")
    async def qq_essence(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询或管理群精华消息。

        Args:
            operation(string): list、add 或 remove。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_essence", operation, params)

    @filter.llm_tool(name="qq_notice")
    async def qq_notice(
        self, event: AstrMessageEvent, operation: str, params: dict
    ) -> str:
        """查询、发布或删除群公告。

        Args:
            operation(string): list、detail、send 或 delete。
            params(object): 当前 operation 的严格参数对象。
        """

        return await self.runtime.execute(event, "qq_notice", operation, params)

    async def terminate(self) -> None:
        """Stop cleanup without deleting persistent plugin data."""

        if self.cleanup_task is not None:
            self.cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.cleanup_task
        logger.info("QQ extension tools terminated")
