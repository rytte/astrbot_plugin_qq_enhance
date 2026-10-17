from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .face_names import QQ_FACE_NAMES, QQ_SUPER_FACE_IDS
from .random_components import parse_random_component

_FIELD_CHAR_LIMIT = 300
_JSON_INPUT_LIMIT = 65536
_RAW_SCAN_LIMIT = 256
# OneBot's ordinary poke types; NapCat reports id=type instead of id=-1.
_POKE_TYPE_NAMES = {
    "1": "戳一戳",
    "2": "比心",
    "3": "点赞",
    "4": "心碎",
    "5": "666",
    "6": "放大招",
}
_CARD_URL_KEYS = (
    "jumpUrl",
    "jump_url",
    "url",
    "qqdocurl",
    "qqdocUrl",
    "source_url",
    "sourceUrl",
    "web_url",
    "webUrl",
    "link",
    "href",
)
_BILIBILI_BVID_RE = re.compile(
    r"(?<![A-Za-z0-9])BV[0-9A-Za-z]{10}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
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


def format_forward_reference(data: Any, *, semanticize_components: bool) -> str:
    """Build a read entry from a real forward segment without fetching content."""

    if not isinstance(data, Mapping):
        return ""
    resource_id = next(
        (
            value
            for key in ("id", "resid", "res_id")
            if isinstance(value := data.get(key), str) and value.strip()
        ),
        "",
    )
    # Keep opaque IDs intact and exclude delimiters that could break the entry.
    if (
        not resource_id
        or len(resource_id) > 512
        or re.search(r'[\s\x00-\x1f\x7f\[\]<>"\\；]', resource_id)
    ):
        return ""
    prefix = (
        "[QQ component|QQ合并转发消息；"
        if semanticize_components
        else "[QQ ForwardRef "
    )
    params = json.dumps(
        {"res_id": resource_id}, ensure_ascii=False, separators=(",", ":")
    )
    return (
        f"{prefix}res_id={resource_id}；如需读取正文，"
        f'调用 qq_forward_get(operation="get", params={params})]'
    )


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
    query = ""
    if hostname.lower().rstrip(".") in {"acfun.cn", "m.acfun.cn", "www.acfun.cn"}:
        try:
            params = parse_qs(
                parsed.query,
                keep_blank_values=False,
                max_num_fields=32,
            )
        except ValueError:
            params = {}
        ac_id = params.get("ac", [""])[0]
        if ac_id.isdecimal() and 0 < len(ac_id) <= 20 and int(ac_id) > 0:
            query = urlencode({"ac": ac_id})
    return _clean_text(urlunsplit((parsed.scheme, netloc, parsed.path, query, "")))


def _extract_bilibili_bvid(value: Any) -> str:
    """Extract one Bilibili BV identifier from an already allowlisted field.

    Only a bounded scalar is inspected.  The caller decides which card fields are
    allowlisted, so arbitrary nested card data is never searched or exposed.
    """

    text = _clean_text(value, 4096)
    try:
        hostname = (urlsplit(text).hostname or "").lower()
    except ValueError:
        return ""
    if not (
        hostname == "b23.tv"
        or hostname.endswith(".bilibili.com")
        or hostname == "bilibili.com"
    ):
        return ""
    match = _BILIBILI_BVID_RE.search(text)
    return f"BV{match.group(0)[2:]}" if match else ""


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
    fields.extend(("链接", payload.get(key)) for key in _CARD_URL_KEYS)
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
                    *(("链接", item.get(key)) for key in _CARD_URL_KEYS),
                )
            )

    details = []
    seen = set()
    link_details = []
    link_seen = set()
    bvids = []
    for field_label, raw_value in fields:
        if field_label == "链接":
            text = _display_url(raw_value)
            if text and text not in link_seen:
                link_seen.add(text)
                link_details.append(f"链接：{text}")
            bvid = _extract_bilibili_bvid(raw_value) if text else ""
            if bvid and bvid not in bvids:
                bvids.append(bvid)
            continue
        text = _clean_text(raw_value)
        if not text or text in seen:
            continue
        seen.add(text)
        if len(details) < 8:
            details.append(f"{field_label}：{text}")
    if link_details:
        details = details[:7]
        details.append(link_details[0])
    if bvids and len(details) < 8:
        details.append(f"BV号：{bvids[0]}")
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
    random_component = parse_random_component(component)
    if random_component is not None:
        return random_component.kind
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


def _describe_component(
    component: Any,
    *,
    image_is_animated: bool | None = None,
    image_record: Mapping[str, Any] | None = None,
    animation_inspection_enabled: bool = True,
) -> str:
    """Convert one supported OneBot message component into semantic text.

    Args:
        component: Raw OneBot message component.
        image_is_animated: Animation state verified from the prepared image file.
        image_record: Real saved reference and dimensions, after saving the image.
        animation_inspection_enabled: Whether to advertise animation inspection.

    Returns:
        A semantic annotation, or an empty string for components already handled by
        AstrBot as text, mentions, or replies.
    """

    if not isinstance(component, Mapping):
        return ""
    component_type = _clean_text(component.get("type"), 40).lower()
    data = component.get("data")
    if not isinstance(data, Mapping):
        return ""

    random_component = parse_random_component(component)
    if random_component is not None:
        label = {
            "dice": "QQ骰子",
            "rps": "QQ猜拳",
            "basketball": "QQ篮球",
        }[random_component.kind]
        if random_component.result is not None:
            if random_component.kind == "dice":
                content = f"{label}：结果 {random_component.result}"
            else:
                content = f"{label}：{random_component.result}"
        elif random_component.result_provided:
            content = f"{label}：结果未知"
        else:
            content = label
        return format_component_semantics(content)

    if component_type == "face":
        raw = data.get("raw")
        face_text = raw.get("faceText") if isinstance(raw, Mapping) else ""
        name = _clean_text(face_text).removeprefix("/")
        face_id = _clean_text(data.get("id"), 40)
        mapped_name = QQ_FACE_NAMES.get(face_id, "")
        label = name or mapped_name
        # NapCat's raw faceType describes this occurrence, including ordinary
        # variants of IDs that also have a super animation in the catalog.
        face_type = (
            _clean_text(raw.get("faceType"), 40) if isinstance(raw, Mapping) else ""
        )
        is_super = (
            face_type == "3"
            if face_type in {"1", "2", "3"}
            else face_id in QQ_SUPER_FACE_IDS
        )
        kind = "QQ超级表情" if is_super else "QQ表情"
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
        return format_component_semantics(f"{kind}：{label}{suffix}")

    if component_type in {"mface", "image"}:
        summary = _clean_text(data.get("summary")).strip("[]").removeprefix("/")
        if summary in {"图片", "动画表情", "收藏表情", "商城表情"}:
            summary = ""
        is_market_face = component_type == "mface" or any(
            key in data for key in ("emoji_id", "emoji_package_id", "key")
        )
        if is_market_face:
            content = f"QQ商城表情：{summary or '名称未知'}"
            if image_is_animated is True:
                content += "；动态"
        else:
            is_sticker = (
                _clean_text(data.get("sub_type", data.get("subType")), 40) == "1"
            )
            if is_sticker:
                label = "QQ动态表情包" if image_is_animated is True else "QQ表情包"
            else:
                label = "QQ动图" if image_is_animated is True else "QQ图片"
            content = f"{label}：{summary}" if summary else label
        if image_record:
            image_ref = image_record["image_ref"]
            content += f"；image_ref={image_ref}"
            content += f"；{image_record['width']}x{image_record['height']}"
            if image_ref.startswith("gimg_"):
                content += "；群聊短期缓存，可能过期或被淘汰"
            content += (
                '；如需查看原图，调用 qq_media(operation="inspect", '
                f'params={{"image_ref":"{image_ref}"}})'
            )
            if image_is_animated is True and animation_inspection_enabled:
                content += (
                    '；如需查看动画，调用 qq_media(operation="inspect_animation", '
                    f'params={{"image_ref":"{image_ref}"}})'
                )
        return format_component_semantics(content)

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
        poke_type = _clean_text(data.get("type"), 40)
        poke_id = _clean_text(data.get("id"), 40)
        name = _clean_text(data.get("name")) or _POKE_TYPE_NAMES.get(poke_type, "")
        if not name:
            identifiers = []
            if poke_type:
                identifiers.append(f"类型 {poke_type}")
            if poke_id:
                identifiers.append(f"ID {poke_id}")
            name = (
                f"名称未知，{'，'.join(identifiers)}，不要根据编号猜测含义"
                if identifiers
                else "名称和编号均未知"
            )
        return format_component_semantics(f"QQ互动表情：{name}")
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
    image_animations: Mapping[int, bool] | None = None,
    image_records: Mapping[int, Mapping[str, Any]] | None = None,
    animation_inspection_enabled: bool = True,
) -> str:
    """Describe one supported NapCat message or targeted poke notice.

    Args:
        raw_event: Original aiocqhttp event retained by AstrBot.
        self_id: Current bot QQ ID.
        semanticize_components: Whether components should be described. Forward
            read entries are retained with the standalone format when false.
        respond_to_poke: Whether a poke targeting this bot should wake the model.
        max_components: Maximum number of raw message components to inspect.
        max_chars: Maximum semantic text appended to the model prompt.
        image_animations: Verified animation states keyed by raw message-segment index.
        image_records: Saved image references and sizes keyed by the same index.
        animation_inspection_enabled: Whether to advertise animation inspection.

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
        group_id = _clean_text(raw_event.get("group_id") or "", 40)
        scope = f"群聊（群号 {group_id}）" if group_id else "私聊"
        actor = f"用户 {actor_id} 戳了你" if actor_id else "有人戳了你"
        content = f"QQ互动：{scope}，{actor}"
        return format_component_semantics(content)

    if post_type not in {None, "message"}:
        return ""
    descriptions = []
    references = []
    reference_fallbacks = {}
    components = raw_event.get("message")
    if isinstance(components, list):
        for index, component in enumerate(components[:max_components]):
            if (
                isinstance(component, Mapping)
                and _clean_text(component.get("type"), 40).lower() == "forward"
            ):
                reference = format_forward_reference(
                    component.get("data"),
                    semanticize_components=semanticize_components,
                )
                if reference:
                    if reference not in references:
                        references.append(reference)
                    continue
            description = (
                _describe_component(
                    component,
                    image_is_animated=(image_animations or {}).get(index),
                    image_record=(image_records or {}).get(index),
                    animation_inspection_enabled=animation_inspection_enabled,
                )
                if semanticize_components
                else ""
            )
            if description:
                if (image_records or {}).get(index):
                    # Keep tool entries whole, just like forward read entries.
                    if description not in references:
                        references.append(description)
                        reference_fallbacks[description] = _describe_component(
                            component,
                            image_is_animated=(image_animations or {}).get(index),
                        )
                else:
                    descriptions.append(description)
    if semanticize_components and _contains_wallet_element(raw_event.get("raw")):
        descriptions.append(
            format_component_semantics("QQ红包消息（仅识别，不能代领）")
        )
    # Reserve complete read entries before truncating ordinary semantics: cutting
    # a resource ID or tool call would leave an unusable reference in history.
    selected_references = []
    remaining = max_chars
    for reference in references:
        cost = len(reference) + bool(selected_references)
        if cost <= remaining:
            selected_references.append(reference)
            remaining -= cost
        elif reference in reference_fallbacks:
            descriptions.append(reference_fallbacks[reference])
    if selected_references:
        remaining = max(0, remaining - 1)
    text = " ".join(descriptions)
    if len(text) > remaining:
        text = text[: remaining - 1] + "…" if remaining else ""
    return " ".join([*selected_references, *([text] if text else [])])
