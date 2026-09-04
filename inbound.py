from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from .face_names import QQ_FACE_NAMES

_FIELD_CHAR_LIMIT = 300
_JSON_INPUT_LIMIT = 65536
_RAW_SCAN_LIMIT = 256
_XML_TEXT_RE = re.compile(
    r"(?:brief|summary|title|name|desc)\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def format_component_semantics(content: str) -> str:
    """Wrap trusted QQ component semantics in the reserved text format.

    Args:
        content: Human-readable component semantics without outer delimiters.

    Returns:
        Canonical plugin-generated QQ component text.
    """

    return f"[QQ component|{content}]"


def _clean_text(value: Any, limit: int = _FIELD_CHAR_LIMIT) -> str:
    """Normalize an untrusted scalar for a bounded semantic annotation.

    Args:
        value: Incoming OneBot field value.
        limit: Maximum returned character count.

    Returns:
        Collapsed text, or an empty string for unsupported values.
    """

    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = " ".join(html.unescape(str(value)).replace("\x00", "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _display_url(value: Any) -> str:
    """Return a bounded URL without credentials, query parameters, or fragments.

    Args:
        value: Incoming URL field.

    Returns:
        A display-safe URL or an empty string.
    """

    text = _clean_text(value, 1000)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    hostname = parsed.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port else hostname
    return _clean_text(urlunsplit((parsed.scheme, netloc, parsed.path, "", "")))


def _decode_card_payload(value: Any) -> Mapping[str, Any] | None:
    """Decode at most two JSON string layers from an incoming card payload.

    Args:
        value: OneBot JSON, mini-app, or Ark payload.

    Returns:
        The decoded mapping, or ``None`` when the payload is not a bounded object.
    """

    current = value
    for _ in range(2):
        if isinstance(current, Mapping):
            return current
        if not isinstance(current, str) or len(current) > _JSON_INPUT_LIMIT:
            return None
        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            return None
    return current if isinstance(current, Mapping) else None


def _contains_red_packet_marker(value: Any) -> bool:
    """Detect explicit red-packet markers in a bounded structured payload scan.

    Args:
        value: Decoded or encoded QQ card payload.

    Returns:
        Whether the payload contains an explicit red-packet marker.
    """

    payload = _decode_card_payload(value)
    if payload is None:
        return False
    pending = [payload]
    scanned = 0
    while pending and scanned < _RAW_SCAN_LIMIT:
        current = pending.pop()
        scanned += 1
        if isinstance(current, Mapping):
            for key, item in current.items():
                key_text = str(key).lower()
                if any(
                    marker in key_text
                    for marker in ("redpacket", "red_packet", "redpack", "wallet")
                ):
                    return True
                pending.append(item)
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            pending.extend(current)
        elif isinstance(current, str):
            lowered = current[:_FIELD_CHAR_LIMIT].lower()
            if any(
                marker in lowered
                for marker in ("红包", "redpacket", "red_packet", "redpack", "wallet")
            ):
                return True
    return False


def _describe_card(value: Any, default_label: str) -> str:
    """Extract allowlisted human-facing fields from a QQ structured card.

    Args:
        value: Raw JSON-like card payload.
        default_label: Label used when the payload has no recognizable fields.

    Returns:
        A bounded semantic annotation that never includes arbitrary card fields.
    """

    payload = _decode_card_payload(value)
    if payload is None:
        return format_component_semantics(default_label)
    red_packet = _contains_red_packet_marker(payload)
    label = "QQ红包卡片（仅识别，不能代领）" if red_packet else default_label

    fields: list[tuple[str, Any]] = [
        ("标题", payload.get("title")),
        ("提示", payload.get("prompt")),
        ("说明", payload.get("desc")),
        ("摘要", payload.get("summary")),
        ("内容", payload.get("content")),
        ("名称", payload.get("name")),
    ]
    meta = payload.get("meta")
    if isinstance(meta, Mapping):
        for item in list(meta.values())[:8]:
            if not isinstance(item, Mapping):
                continue
            if (
                payload.get("app") == "com.tencent.contact.lua"
                and payload.get("view") == "contact"
            ):
                contact_id = _clean_text(item.get("contact"), 40)
                card_type = ""
                verified_contact_link = False
                link_source = ""
                jump_url = _clean_text(item.get("jumpUrl"), 4096)
                if jump_url:
                    try:
                        parsed = urlsplit(jump_url)
                        query = parse_qs(
                            parsed.query,
                            keep_blank_values=False,
                            max_num_fields=32,
                        )
                    except ValueError:
                        parsed = None
                        query = {}
                    if (
                        parsed is not None
                        and parsed.scheme == "mqqapi"
                        and parsed.netloc == "card"
                        and parsed.path == "/show_pslcard"
                    ):
                        verified_contact_link = True
                        card_type = _clean_text(query.get("card_type", [""])[0], 20)
                        link_source = _clean_text(query.get("source", [""])[0], 40)
                        link_id = _clean_text(query.get("uin", [""])[0], 40)
                        if link_id:
                            contact_id = link_id
                tag = _clean_text(item.get("tag"), 40)
                if not card_type:
                    if tag == "群名片":
                        card_type = "group"
                    elif tag in {"QQ号", "联系人名片"}:
                        card_type = "person"
                    elif (
                        tag == "推荐好友"
                        and payload.get("bizsrc") == "cardshare.cardshare"
                        and verified_contact_link
                        and link_source == "sharecard"
                    ):
                        card_type = "person"
                if (
                    card_type in {"group", "person"}
                    and contact_id.isdecimal()
                    and 0 < len(contact_id) <= 20
                    and int(contact_id) > 0
                ):
                    id_label = "群号" if card_type == "group" else "QQ号"
                    if not red_packet:
                        label = "QQ群名片" if card_type == "group" else "QQ联系人名片"
                    fields[0:0] = [
                        (id_label, contact_id),
                        ("名称", item.get("nickname")),
                    ]
            fields.extend(
                (
                    ("标题", item.get("title")),
                    ("说明", item.get("desc")),
                    ("摘要", item.get("summary")),
                    ("内容", item.get("content")),
                    ("名称", item.get("name")),
                    ("标签", item.get("tag")),
                    ("链接", item.get("jumpUrl") or item.get("url")),
                )
            )

    details = []
    seen = set()
    for field_label, raw_value in fields:
        text = (
            _display_url(raw_value) if field_label == "链接" else _clean_text(raw_value)
        )
        if not text or text in seen:
            continue
        seen.add(text)
        details.append(f"{field_label}：{text}")
        if len(details) == 8:
            break
    content = f"{label}：{'；'.join(details)}" if details else label
    return format_component_semantics(content)


def _contains_wallet_element(value: Any) -> bool:
    """Detect a NapCat wallet element in a bounded raw NT message scan.

    Args:
        value: NapCat's debug-only raw message object.

    Returns:
        Whether an explicit wallet message marker was found.
    """

    pending = [value]
    scanned = 0
    while pending and scanned < _RAW_SCAN_LIMIT:
        current = pending.pop()
        scanned += 1
        if isinstance(current, Mapping):
            lowered = {str(key).lower(): item for key, item in current.items()}
            if lowered.get("msgtype") in {10, "10"}:
                return True
            if lowered.get("elementtype") in {9, "9"}:
                return True
            if lowered.get("subelementtype") in {16, "16"}:
                return True
            if lowered.get("busiid") in {81, "81", 2602, "2602"}:
                return True
            if lowered.get("walletelement") is not None:
                return True
            pending.extend(current.values())
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            pending.extend(current)
    return False


def is_red_packet_event(raw_event: Any, max_components: int) -> bool:
    """Check whether a NapCat message explicitly represents a QQ red packet.

    Args:
        raw_event: Original aiocqhttp event retained by AstrBot.
        max_components: Maximum number of OneBot components to inspect.

    Returns:
        Whether a wallet element or structured red-packet card was found.
    """

    if not isinstance(raw_event, Mapping) or raw_event.get("post_type") not in {
        None,
        "message",
    }:
        return False
    if _contains_wallet_element(raw_event.get("raw")):
        return True
    components = raw_event.get("message")
    if not isinstance(components, list):
        return False
    for component in components[:max_components]:
        if not isinstance(component, Mapping):
            continue
        component_type = _clean_text(component.get("type"), 40).lower()
        data = component.get("data")
        if not isinstance(data, Mapping):
            continue
        if component_type in {"json", "miniapp"} and _contains_red_packet_marker(
            data.get("data")
        ):
            return True
        if component_type == "xml":
            xml_text = data.get("data")
            if isinstance(xml_text, str) and "红包" in xml_text[:_JSON_INPUT_LIMIT]:
                return True
    return False


def get_inbound_component_type(component: Any) -> str:
    """Return the model-facing type of a supported OneBot component.

    Args:
        component: Raw OneBot message component.

    Returns:
        The verified semantic type, or an empty string when unsupported.
    """

    if not isinstance(component, Mapping):
        return ""
    component_type = _clean_text(component.get("type"), 40).lower()
    data = component.get("data")
    if not isinstance(data, Mapping):
        return ""
    if component_type == "record":
        return "voice"
    if component_type == "face":
        return "face"
    if component_type in {"mface", "image"}:
        if component_type == "mface" or any(
            key in data for key in ("emoji_id", "emoji_package_id", "key")
        ):
            return "market_face"
        return "image"
    if component_type in {
        "video",
        "file",
        "music",
        "contact",
        "location",
        "share",
        "forward",
        "onlinefile",
        "flashtransfer",
        "dice",
        "rps",
        "poke",
    }:
        return {
            "onlinefile": "online_file",
            "flashtransfer": "flash_transfer",
        }.get(component_type, component_type)
    if component_type in {"json", "miniapp"}:
        description = _describe_card(
            data.get("data"),
            "QQ JSON卡片" if component_type == "json" else "QQ小程序卡片",
        )
        if description.startswith("[QQ component|QQ红包卡片"):
            return "red_packet"
        if description.startswith(
            ("[QQ component|QQ群名片", "[QQ component|QQ联系人名片")
        ):
            return "contact"
        return "json_card" if component_type == "json" else "miniapp"
    if component_type == "xml":
        xml_text = data.get("data")
        if (
            isinstance(xml_text, str)
            and len(xml_text) <= _JSON_INPUT_LIMIT
            and "红包" in xml_text
        ):
            return "red_packet"
        return "xml_card"
    return ""


def _describe_component(component: Any) -> str:
    """Convert one supported OneBot message component into semantic text.

    Args:
        component: Raw OneBot message component.

    Returns:
        A semantic annotation, or an empty string for components already handled by
        AstrBot as text, mentions, replies, or ordinary images.
    """

    if not isinstance(component, Mapping):
        return ""
    component_type = _clean_text(component.get("type"), 40).lower()
    data = component.get("data")
    if not isinstance(data, Mapping):
        return ""

    if component_type == "face":
        raw = data.get("raw")
        face_text = raw.get("faceText") if isinstance(raw, Mapping) else ""
        name = _clean_text(face_text).removeprefix("/")
        face_id = _clean_text(data.get("id"), 40)
        mapped_name = QQ_FACE_NAMES.get(face_id, "")
        label = name or mapped_name
        if not label:
            label = (
                f"名称未知，ID {face_id}，不要根据 ID 猜测含义"
                if face_id
                else "名称和 ID 均未知"
            )
        chain_count = data.get("chainCount")
        suffix = (
            f"，连击×{chain_count}"
            if isinstance(chain_count, int)
            and not isinstance(chain_count, bool)
            and chain_count > 1
            else ""
        )
        return format_component_semantics(f"QQ表情：{label}{suffix}")

    if component_type in {"mface", "image"}:
        summary = _clean_text(data.get("summary")).strip("[]").removeprefix("/")
        is_market_face = component_type == "mface" or any(
            key in data for key in ("emoji_id", "emoji_package_id", "key")
        )
        if is_market_face:
            return format_component_semantics(f"QQ商城表情：{summary or '名称未知'}")
        if summary and summary not in {"图片", "动画表情"}:
            return format_component_semantics(f"图片描述：{summary}")
        return ""

    if component_type == "video":
        return format_component_semantics("视频消息")
    if component_type == "file":
        name = _clean_text(
            data.get("name") or data.get("file_name") or data.get("file"), 160
        )
        return format_component_semantics(f"文件：{name}" if name else "文件")
    if component_type == "music":
        title = _clean_text(data.get("title"))
        content = _clean_text(data.get("content"))
        platform = _clean_text(data.get("type"), 30)
        music_id = _clean_text(data.get("id"), 100)
        details = [item for item in (title, content) if item]
        if not details and music_id:
            details.append(f"{platform or '平台'} ID {music_id}")
        content = f"音乐卡片：{'；'.join(details)}" if details else "音乐卡片"
        return format_component_semantics(content)
    if component_type == "poke":
        return format_component_semantics("QQ互动：戳一戳")
    if component_type == "dice":
        result = _clean_text(data.get("result"), 30)
        content = f"QQ骰子：结果 {result}" if result else "QQ骰子"
        return format_component_semantics(content)
    if component_type == "rps":
        result = _clean_text(data.get("result"), 30)
        gesture = {"1": "布", "2": "剪刀", "3": "石头"}.get(result)
        if gesture:
            return format_component_semantics(f"QQ猜拳：{gesture}")
        content = "QQ猜拳：结果未知" if result else "QQ猜拳"
        return format_component_semantics(content)
    if component_type == "contact":
        contact_type = _clean_text(data.get("type"), 30)
        contact_id = _clean_text(data.get("id"), 100)
        label = "群名片" if contact_type == "group" else "联系人名片"
        content = f"QQ{label}：{contact_id}" if contact_id else f"QQ{label}"
        return format_component_semantics(content)
    if component_type == "location":
        title = _clean_text(data.get("title"))
        content = _clean_text(data.get("content"))
        latitude = _clean_text(data.get("lat"), 40)
        longitude = _clean_text(data.get("lon"), 40)
        coordinates = (
            f"纬度 {latitude}，经度 {longitude}" if latitude and longitude else ""
        )
        details = [item for item in (title, content, coordinates) if item]
        content = f"QQ位置：{'；'.join(details)}" if details else "QQ位置"
        return format_component_semantics(content)
    if component_type == "share":
        title = _clean_text(data.get("title"))
        content = _clean_text(data.get("content"))
        url = _display_url(data.get("url"))
        details = [item for item in (title, content, url) if item]
        content = f"QQ链接分享：{'；'.join(details)}" if details else "QQ链接分享"
        return format_component_semantics(content)
    if component_type == "json":
        return _describe_card(data.get("data"), "QQ JSON卡片")
    if component_type == "miniapp":
        return _describe_card(data.get("data"), "QQ小程序卡片")
    if component_type == "xml":
        xml_text = data.get("data")
        if not isinstance(xml_text, str) or len(xml_text) > _JSON_INPUT_LIMIT:
            return format_component_semantics("QQ XML卡片")
        details = []
        for match in _XML_TEXT_RE.finditer(xml_text):
            text = _clean_text(match.group(1))
            if text and text not in details:
                details.append(text)
            if len(details) == 4:
                break
        label = "QQ红包卡片（仅识别，不能代领）" if "红包" in xml_text else "QQ XML卡片"
        content = f"{label}：{'；'.join(details)}" if details else label
        return format_component_semantics(content)
    if component_type == "forward":
        return format_component_semantics("QQ合并转发消息")
    if component_type == "onlinefile":
        name = _clean_text(data.get("fileName"), 160)
        label = "在线文件夹" if data.get("isDir") is True else "在线文件"
        content = f"QQ{label}：{name}" if name else f"QQ{label}"
        return format_component_semantics(content)
    if component_type == "flashtransfer":
        return format_component_semantics("QQ闪传文件")
    return ""


def describe_inbound_event(
    raw_event: Any,
    self_id: str,
    *,
    semanticize_components: bool,
    respond_to_poke: bool,
    max_components: int,
    max_chars: int,
) -> str:
    """Describe one supported NapCat message or targeted poke notice.

    Args:
        raw_event: Original aiocqhttp event retained by AstrBot.
        self_id: Current bot QQ ID.
        semanticize_components: Whether message components should be described.
        respond_to_poke: Whether a poke targeting this bot should wake the model.
        max_components: Maximum number of raw message components to inspect.
        max_chars: Maximum semantic text appended to the model prompt.

    Returns:
        Bounded semantic text, or an empty string when the event should not be
        enriched.
    """

    if not isinstance(raw_event, Mapping):
        return ""
    post_type = raw_event.get("post_type")
    if post_type == "notice":
        if not respond_to_poke:
            return ""
        if (
            raw_event.get("notice_type") != "notify"
            or raw_event.get("sub_type") != "poke"
        ):
            return ""
        target_id = _clean_text(raw_event.get("target_id"), 40)
        actor_id = _clean_text(
            raw_event.get("user_id") or raw_event.get("sender_id"), 40
        )
        if not self_id or target_id != str(self_id) or actor_id == str(self_id):
            return ""
        content = (
            f"QQ互动：用户 {actor_id} 戳了你" if actor_id else "QQ互动：有人戳了你"
        )
        return format_component_semantics(content)

    if not semanticize_components or post_type not in {None, "message"}:
        return ""
    descriptions = []
    components = raw_event.get("message")
    if isinstance(components, list):
        for component in components[:max_components]:
            description = _describe_component(component)
            if description:
                descriptions.append(description)
    if _contains_wallet_element(raw_event.get("raw")):
        descriptions.append(
            format_component_semantics("QQ红包消息（仅识别，不能代领）")
        )
    text = " ".join(descriptions)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
