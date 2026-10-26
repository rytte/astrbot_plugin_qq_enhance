from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.agent.tool import ToolSet
from astrbot.core.tools.message_tools import SendMessageToUserTool
from astrbot_plugin_qq_enhance.debounce_runtime import ResumedMessageEvent
from astrbot_plugin_qq_enhance.errors import QQToolError
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import validate_config
from astrbot_plugin_qq_enhance.storage import Storage
from astrbot_plugin_qq_enhance.temporary_session import TURN_KEY, TemporarySessions


class PrivateEvent:
    def __init__(self, user_id="20001", platform_id="platform-a", self_id="90001"):
        self.user_id = user_id
        self.platform_id = platform_id
        self.self_id = self_id
        self.unified_msg_origin = f"{platform_id}:FriendMessage:{user_id}"
        self.extras = {}
        self.stopped = False
        self.admin = False
        self.message_obj = SimpleNamespace(
            raw_message={
                "post_type": "message",
                "message_type": "private",
                # Some implementations also use friend for non-friend messages.
                "sub_type": "friend",
                "group_id": 30001,
            }
        )
        self.send = AsyncMock()

    def get_platform_name(self):
        return "aiocqhttp"

    def get_platform_id(self):
        return self.platform_id

    def get_sender_id(self):
        return self.user_id

    def get_sender_name(self):
        return "临时用户"

    def get_self_id(self):
        return self.self_id

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value

    def stop_event(self):
        self.stopped = True

    def is_admin(self):
        return self.admin


@pytest_asyncio.fixture
async def sessions(tmp_path):
    storage = Storage(tmp_path / "data.sqlite3")
    await storage.initialize()
    config = validate_config(
        {
            "temporary_sessions": {
                "max_replies": 2,
                "admin_user_ids": ["10001", "10002"],
            },
        }
    )
    return TemporarySessions(
        SimpleNamespace(send_message=AsyncMock(return_value=True)),
        config,
        storage,
        SimpleNamespace(call_action=AsyncMock(return_value=[])),
    )


def message(text="回复"):
    return MessageChain([Plain(text)])


async def state(sessions, event=None):
    event = event or PrivateEvent()
    return await sessions.storage.get_temporary_session(
        event.platform_id, event.self_id, event.user_id
    )


@pytest.mark.asyncio
async def test_default_policy_allows_three_successful_replies(sessions):
    sessions.config["temporary_sessions"] = validate_config(None)["temporary_sessions"]
    assert sessions.config["temporary_sessions"]["limit_replies"] is True
    assert sessions.config["temporary_sessions"]["max_replies"] == 3
    for _ in range(3):
        event = PrivateEvent()
        await sessions.prepare(event)
        assert not event.stopped
        await event.send(message())
    fourth = PrivateEvent()
    await sessions.prepare(fourth)
    assert fourth.stopped
    assert (await state(sessions))["replies"] == 3


@pytest.mark.asyncio
async def test_disabled_limit_allows_native_and_tools_and_keeps_notifications(sessions):
    sessions.config["temporary_sessions"].update(
        limit_replies=False, max_replies=0, notify_admins=True
    )
    for _ in range(2):
        await sessions.storage.record_temporary_reply("platform-a", "90001", "20001")
    for kind in ("native", "qq_tool", "builtin_tool"):
        event = PrivateEvent()
        await sessions.prepare(event)
        assert not event.stopped
        if kind == "native":
            await event.send(message())
        elif kind == "qq_tool":
            await sessions.send_action(
                event,
                "send_private_msg",
                {"user_id": 20001},
                AsyncMock(return_value={"message_id": 17}),
            )
        else:
            request = SimpleNamespace(func_tool=ToolSet([SendMessageToUserTool()]))
            sessions.wrap_tools(event, request)
            context = SimpleNamespace(
                context=SimpleNamespace(event=event, context=sessions.context)
            )
            await request.func_tool.tools[0].call(
                context, messages=[{"type": "plain", "text": "你好"}]
            )
        await event.send(message("同一轮的后续分段"))
    assert (await state(sessions))["replies"] == 5
    # Two administrator reminders and one built-in reply were delivered.
    assert sessions.context.send_message.await_count == 3
    reminder = sessions.context.send_message.await_args_list[0].args[1].get_plain_text()
    assert "不限回复次数" in reminder
    sessions.config["temporary_sessions"].update(limit_replies=True, max_replies=3)
    restricted_again = PrivateEvent()
    await sessions.prepare(restricted_again)
    assert restricted_again.stopped
    assert (await state(sessions))["replies"] == 5


@pytest.mark.asyncio
async def test_disabled_limit_does_not_block_on_friend_lookup_failure(sessions):
    sessions.config["temporary_sessions"].update(limit_replies=False, max_replies=0)
    sessions.runtime.call_action.side_effect = RuntimeError("协议端不可用")
    event = PrivateEvent()
    original_send = event.send
    await sessions.prepare(event)
    assert not event.stopped
    await event.send(message())
    original_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_only_successful_turns_count_and_segments_share_one_reply(sessions):
    first = PrivateEvent()
    original_send = first.send
    await sessions.prepare(first)
    await first.send(message("第一段"))
    await first.send(message("第二段"))
    assert original_send.await_count == 2
    assert (await state(sessions))["replies"] == 1

    # Receiving a message without sending anything does not spend a reply.
    ignored = PrivateEvent()
    await sessions.prepare(ignored)
    failed = PrivateEvent()
    failed.send.side_effect = RuntimeError("发送失败")
    await sessions.prepare(failed)
    with pytest.raises(RuntimeError, match="发送失败"):
        await failed.send(message())
    assert (await state(sessions))["replies"] == 1

    second = PrivateEvent()
    await sessions.prepare(second)
    await second.send(message())
    third = PrivateEvent()
    await sessions.prepare(third)
    assert third.stopped
    assert (await state(sessions))["replies"] == 2


@pytest.mark.asyncio
async def test_reply_count_survives_restart_and_regular_cleanup(sessions):
    event = PrivateEvent()
    await sessions.prepare(event)
    await event.send(message())
    sessions.storage = Storage(sessions.storage.database_path)
    await sessions.storage.initialize()
    await sessions.storage.cleanup(1, 1)
    sessions.config["temporary_sessions"]["max_replies"] = 1
    later = PrivateEvent()
    await sessions.prepare(later)
    assert later.stopped
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
async def test_friendship_immediately_removes_exhausted_limit_and_reminders(sessions):
    sessions.config["temporary_sessions"].update(max_replies=0, notify_admins=True)
    denied = PrivateEvent()
    await sessions.prepare(denied)
    assert denied.stopped
    sessions.context.send_message.reset_mock()
    sessions.runtime.call_action.return_value = [{"user_id": 20001}]
    friend = PrivateEvent()
    await sessions.prepare(friend)
    assert not friend.stopped
    assert friend.get_extra(TURN_KEY) is None
    await friend.send(message())
    sessions.context.send_message.assert_not_awaited()
    assert (await state(sessions))["replies"] == 0


@pytest.mark.asyncio
async def test_zero_quota_still_notifies_each_admin_once_across_restart(sessions):
    sessions.config["temporary_sessions"].update(max_replies=0, notify_admins=True)
    sessions.config["request_notifications"]["admin_user_ids"] = ["19999"]
    for _ in range(3):
        event = PrivateEvent()
        await sessions.prepare(event)
        assert event.stopped
        sessions.storage = Storage(sessions.storage.database_path)
    calls = sessions.context.send_message.await_args_list
    assert len(calls) == 2
    assert [call.args[0].session_id for call in calls] == ["10001", "10002"]
    text = calls[0].args[1].get_plain_text()
    assert "20001" in text and "30001" in text and "拒绝临时会话" in text
    assert sessions.config["request_notifications"]["enabled"] is False


@pytest.mark.asyncio
async def test_notification_failure_can_retry_and_does_not_lift_zero_limit(sessions):
    sessions.config["temporary_sessions"].update(max_replies=0, notify_admins=True)
    sessions.context.send_message.side_effect = RuntimeError("离线")
    denied = PrivateEvent()
    await sessions.prepare(denied)
    assert denied.stopped
    assert (await state(sessions))["notified"] == 0
    sessions.context.send_message.side_effect = None
    await sessions.prepare(PrivateEvent())
    assert (await state(sessions))["notified"] == 1


@pytest.mark.asyncio
async def test_admin_initiation_suppresses_reminder_but_keeps_reply_limit(sessions):
    sessions.config["temporary_sessions"].update(max_replies=1, notify_admins=True)
    admin = PrivateEvent(user_id="10001")
    admin.admin = True
    deliver = AsyncMock(return_value={"message_id": 17})
    await sessions.send_action(
        admin, "send_private_msg", {"user_id": 20001, "group_id": 30001}, deliver
    )
    assert (await state(sessions))["bot_initiated"] == 1
    assert (await state(sessions))["replies"] == 0
    sessions.storage = Storage(sessions.storage.database_path)
    followup = PrivateEvent()
    await sessions.prepare(followup)
    await followup.send(message())
    last = PrivateEvent()
    await sessions.prepare(last)
    assert last.stopped
    sessions.context.send_message.assert_not_awaited()
    # An additional proactive send must not reset the recipient's old usage.
    await sessions.send_action(
        admin, "send_private_msg", {"user_id": 20001, "group_id": 30001}, deliver
    )
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
async def test_failed_proactive_send_does_not_suppress_future_reminder(sessions):
    sessions.config["temporary_sessions"]["notify_admins"] = True
    admin = PrivateEvent(user_id="10001")
    admin.admin = True
    with pytest.raises(RuntimeError):
        await sessions.send_action(
            admin,
            "send_private_msg",
            {"user_id": 20001, "group_id": 30001},
            AsyncMock(side_effect=RuntimeError("发送失败")),
        )
    assert (await state(sessions))["bot_initiated"] == 0
    await sessions.prepare(PrivateEvent())
    assert sessions.context.send_message.await_count == 2


@pytest.mark.asyncio
async def test_simultaneous_inputs_cannot_exceed_final_reply(sessions):
    sessions.config["temporary_sessions"]["max_replies"] = 1
    events = [PrivateEvent() for _ in range(3)]
    transports = [event.send for event in events]
    await asyncio.gather(*(sessions.prepare(event) for event in events))
    results = await asyncio.gather(
        *(event.send(message()) for event in events), return_exceptions=True
    )
    assert sum(isinstance(result, QQToolError) for result in results) == 2
    assert sum(transport.await_count for transport in transports) == 1
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
async def test_qq_tool_and_native_segments_share_one_reply(sessions):
    event = PrivateEvent()
    await sessions.prepare(event)
    deliver = AsyncMock(return_value={"message_id": 17})
    for action in (
        "send_private_msg",
        "send_private_forward_msg",
        "upload_private_file",
    ):
        await sessions.send_action(event, action, {"user_id": 20001}, deliver)
    await event.send(message())
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
async def test_builtin_tool_is_request_local_and_shares_native_quota(sessions):
    event = PrivateEvent()
    await sessions.prepare(event)
    original = SendMessageToUserTool()
    shared = ToolSet([original])
    request = SimpleNamespace(func_tool=shared)
    sessions.wrap_tools(event, request)
    wrapped = request.func_tool.tools[0]
    assert wrapped is not original
    assert shared.tools[0] is original
    assert wrapped.parameters == original.parameters
    context = SimpleNamespace(
        context=SimpleNamespace(event=event, context=sessions.context)
    )
    result = await wrapped.call(context, messages=[{"type": "plain", "text": "你好"}])
    assert result.startswith("Message sent to session")
    await event.send(message())
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
async def test_builtin_send_failure_does_not_spend_reply(sessions):
    event = PrivateEvent()
    await sessions.prepare(event)
    request = SimpleNamespace(func_tool=ToolSet([SendMessageToUserTool()]))
    sessions.wrap_tools(event, request)
    context = SimpleNamespace(
        context=SimpleNamespace(event=event, context=sessions.context)
    )
    sessions.context.send_message.return_value = False
    result = await request.func_tool.tools[0].call(
        context, messages=[{"type": "plain", "text": "你好"}]
    )
    assert result.startswith("error:")
    assert (await state(sessions))["replies"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["user", "platform", "bot"])
async def test_identity_isolation(sessions, changed):
    event = PrivateEvent()
    await sessions.prepare(event)
    await event.send(message())
    other = PrivateEvent(
        user_id="20002" if changed == "user" else "20001",
        platform_id="platform-b" if changed == "platform" else "platform-a",
        self_id="90002" if changed == "bot" else "90001",
    )
    assert (await state(sessions, other))["replies"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, "invalid"])
async def test_unknown_friendship_does_not_bypass_finite_limit(sessions, response):
    sessions.runtime.call_action.return_value = response
    event = PrivateEvent()
    await sessions.prepare(event)
    assert event.stopped
    sessions.context.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_send_does_not_spend_reply(sessions):
    event = PrivateEvent()
    await sessions.prepare(event)
    await event.send(message("  "))
    assert (await state(sessions))["replies"] == 0


@pytest.mark.asyncio
async def test_friend_added_while_another_turn_spends_last_reply(sessions):
    sessions.config["temporary_sessions"]["max_replies"] = 1
    events = [PrivateEvent(), PrivateEvent()]
    for event in events:
        await sessions.prepare(event)
    await events[0].send(message())
    sessions.runtime.call_action.return_value = [{"user_id": 20001}]
    await events[1].send(message())
    assert not events[1].stopped
    assert (await state(sessions))["replies"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming_fallback", [False, True])
async def test_native_streamed_segments_count_one_reply(
    sessions, monkeypatch, streaming_fallback
):
    from test_debounce_runtime import source_message

    monkeypatch.setattr("astrbot.core.utils.metrics.Metric.upload", AsyncMock())
    event = source_message()
    event.message_obj.raw_message["message_type"] = "private"
    event.bot.send_private_msg = AsyncMock()
    await sessions.prepare(event)

    async def stream():
        yield message("你好。")
        yield message("继续。")

    await event.send_streaming(stream(), use_fallback=streaming_fallback)
    result = await sessions.storage.get_temporary_session("qq", "99", "7")
    assert result["replies"] == 1
    assert event.bot.send_private_msg.await_count == (2 if streaming_fallback else 1)


@pytest.mark.asyncio
async def test_repeated_debounce_resume_preserves_quota_and_transport_state(
    sessions, monkeypatch
):
    from test_debounce_runtime import source_message

    monkeypatch.setattr("astrbot.core.utils.metrics.Metric.upload", AsyncMock())
    source = source_message()
    source.message_obj.raw_message["message_type"] = "private"
    source.bot.send_private_msg = AsyncMock()
    await sessions.prepare(source)
    plugin = object.__new__(QQEnhancePlugin)
    plugin.temporary_sessions = sessions
    debouncer = SimpleNamespace(closed=False, config={"enabled": True})
    resumed = source
    for _ in range(2):
        resumed = ResumedMessageEvent(resumed, debouncer)
        await plugin.guard_temporary_session(resumed)
    assert resumed.get_extra(TURN_KEY) is source.get_extra(TURN_KEY)

    async def stream():
        yield message()

    await asyncio.wait_for(resumed.send_streaming(stream()), 3)
    assert resumed._has_send_oper
    await sessions.send_action(
        resumed,
        "send_private_msg",
        {"user_id": 7},
        AsyncMock(return_value={"message_id": 17}),
    )
    result = await sessions.storage.get_temporary_session("qq", "99", "7")
    assert result["replies"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["group", "request", "other_platform", "self", "other_instance"]
)
async def test_unrelated_inputs_are_untouched(sessions, kind):
    event = PrivateEvent()
    if kind == "group":
        event.message_obj.raw_message["message_type"] = "group"
    elif kind == "request":
        event.message_obj.raw_message["post_type"] = "request"
    elif kind == "other_platform":
        event.get_platform_name = lambda: "webchat"
    elif kind == "self":
        event.user_id = event.self_id
    else:
        sessions.config["platform"]["platform_id"] = "platform-b"
    await sessions.prepare(event)
    sessions.runtime.call_action.assert_not_awaited()
    assert event.get_extra(TURN_KEY) is None
    assert not event.stopped


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", [0, 2])
async def test_private_notice_response_uses_contact_quota_without_notification(
    sessions, monkeypatch, maximum
):
    from astrbot.core.platform.platform_metadata import PlatformMetadata
    from astrbot_plugin_qq_enhance.notice_context import QQNotice
    from astrbot_plugin_qq_enhance.request_notification import NoticeResponseEvent

    monkeypatch.setattr("astrbot.core.utils.metrics.Metric.upload", AsyncMock())
    sessions.config["temporary_sessions"].update(
        max_replies=maximum, notify_admins=True
    )
    notice = QQNotice(
        kind="notify/poke",
        self_id="90001",
        group_id="",
        user_id="20001",
        occurred_at=1793000000,
        details={},
        description="临时用户戳了机器人",
    )
    platform = SimpleNamespace(
        meta=lambda: PlatformMetadata(
            name="aiocqhttp", id="platform-a", description=""
        ),
        get_client=lambda: SimpleNamespace(),
    )
    owner = SimpleNamespace(
        plugin=SimpleNamespace(context=sessions.context), closed=False
    )
    delivery = SimpleNamespace(umo="platform-a:FriendMessage:20001", notice=notice)
    event = NoticeResponseEvent(owner, platform, delivery, "90001")
    await sessions.prepare(event)
    assert event.is_stopped() == (maximum == 0)
    sessions.context.send_message.assert_not_awaited()
    if maximum:
        await event.send(message())
        assert (await state(sessions))["replies"] == 1
        assert sessions.context.send_message.await_args.args[0].session_id == "20001"


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("value", [-2, -1, 1.0, "1", True, None])
def test_invalid_quota_is_rejected(value, enabled):
    with pytest.raises(
        ValueError, match="temporary_sessions.max_replies 必须是大于等于 0 的整数"
    ):
        validate_config(
            {"temporary_sessions": {"limit_replies": enabled, "max_replies": value}}
        )


@pytest.mark.parametrize("value", [0, 1, "false", None])
def test_reply_limit_switch_requires_boolean(value):
    with pytest.raises(
        ValueError, match="temporary_sessions.limit_replies 必须是布尔值"
    ):
        validate_config({"temporary_sessions": {"limit_replies": value}})


def test_notification_requires_recipients_but_not_request_notifications():
    with pytest.raises(ValueError, match="temporary_sessions.admin_user_ids"):
        validate_config(
            {
                "temporary_sessions": {"notify_admins": True},
                "request_notifications": {"admin_user_ids": ["10001"]},
            }
        )
    config = validate_config(
        {
            "temporary_sessions": {
                "notify_admins": True,
                "admin_user_ids": ["10002"],
            },
        }
    )
    assert config["request_notifications"]["enabled"] is False
    assert config["request_notifications"]["admin_user_ids"] == []
    assert config["temporary_sessions"]["admin_user_ids"] == ["10002"]


@pytest.mark.parametrize(
    "value", [None, "10001", [10001], ["not-a-qq"], ["0"], ["-1"], ["10001", "10001"]]
)
def test_temporary_notification_recipients_are_validated(value):
    with pytest.raises(ValueError, match="temporary_sessions.admin_user_ids"):
        validate_config({"temporary_sessions": {"admin_user_ids": value}})
