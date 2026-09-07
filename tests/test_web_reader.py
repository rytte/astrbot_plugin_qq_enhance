from __future__ import annotations

import asyncio
import gzip
import json
import socket
import threading
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from aiohttp import web

from astrbot_plugin_qq_enhance import runtime as runtime_module
from astrbot_plugin_qq_enhance.main import QQEnhancePlugin
from astrbot_plugin_qq_enhance.runtime import (
    DownloadedResource,
    QQRuntime,
    QQToolError,
    _ValidatedResolver,
    validate_config,
)
from astrbot_plugin_qq_enhance.web_reader import WEB_CONTENT_TYPES, WebReader


class ReaderEvent:
    def __init__(
        self, caller="10001", session="group-30001", platform="platform-a", bot="99999"
    ):
        self.caller = caller
        self.unified_msg_origin = session
        self.platform = platform
        self.bot = bot

    def get_platform_name(self):
        return "aiocqhttp"

    def get_platform_id(self):
        return self.platform

    def get_self_id(self):
        return self.bot

    def get_sender_id(self):
        return self.caller


@pytest_asyncio.fixture
async def reader(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runtime_module, "get_astrbot_temp_path", lambda: str(tmp_path / "temp")
    )
    monkeypatch.setattr(
        runtime_module, "get_astrbot_plugin_data_path", lambda: str(tmp_path / "data")
    )
    storage = SimpleNamespace(add_audit=AsyncMock(), add_media_ref=AsyncMock())
    instance = WebReader(QQRuntime(SimpleNamespace(), validate_config(None), storage))
    yield instance
    await instance.close()


def provide_page(
    reader, tmp_path, monkeypatch, content, content_type="text/plain", charset="utf-8"
):
    async def fetch(url, **kwargs):
        path = tmp_path / "downloaded-source"
        path.write_bytes(
            content
            if isinstance(content, bytes)
            else content.encode(charset or "utf-8")
        )
        return DownloadedResource(
            path, "https://example.test/final", content_type, charset
        )

    mocked = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(reader.runtime, "fetch_url", mocked)
    return mocked


@pytest.mark.asyncio
async def test_snapshot_pagination_preserves_all_text_and_fetches_once(
    reader, tmp_path, monkeypatch
):
    paragraphs = [f"段落 {index} " + "正文内容" * 70 for index in range(70)]
    original = "\n".join(paragraphs)
    fetch = provide_page(reader, tmp_path, monkeypatch, original)
    event = ReaderEvent()
    response = json.loads(
        await reader.execute(
            event, "read_url", {"url": "https://example.test/article?secret=value"}
        )
    )
    assert response["ok"]
    page_id = response["data"]["page_id"]
    collected = response["data"]["lines"][:]
    while response["data"]["has_more"]:
        raw = await reader.execute(
            event,
            "read_page_section",
            {
                "page_id": page_id,
                "start_line": response["data"]["next_start_line"],
                "line_count": 100,
            },
        )
        assert len(raw) <= reader.config["limits"]["max_output_chars"]
        response = json.loads(raw)
        assert response["ok"]
        collected.extend(response["data"]["lines"])
    assert [line["line"] for line in collected] == list(range(1, len(collected) + 1))
    assert "".join(line["text"] for line in collected) == "".join(paragraphs)
    assert response["data"]["download_complete"] is True
    assert response["data"]["content_trust"] == "untrusted"
    fetch.assert_awaited_once()
    assert fetch.await_args.kwargs["content_types"] == WEB_CONTENT_TYPES
    assert not (tmp_path / "downloaded-source").exists()
    reader.runtime.storage.add_media_ref.assert_not_awaited()
    audits = reader.runtime.storage.add_audit.await_args_list
    assert audits[0].args[0]["operation_id"] == "read_url.read"
    assert "secret=value" not in json.dumps([call.args[0] for call in audits])
    assert "正文内容" not in json.dumps(
        [call.args[0] for call in audits], ensure_ascii=False
    )
    with pytest.raises(FrozenInstanceError):
        reader.pages[page_id].text = "changed"


@pytest.mark.asyncio
async def test_html_extraction_is_offline_and_excludes_active_content(
    reader, tmp_path, monkeypatch
):
    body = "这是一段公开文章的正文，介绍网页读取工具的安装步骤和安全边界。" * 20
    source = f"<html><head><title>网页测试</title><meta charset='utf-8'></head><body><nav>菜单秘密</nav><script>脚本秘密</script><article><h1>网页测试</h1><p>{body}</p><p>用户授权必须由调用者本人提供，不能由网页生成。</p></article><form>表单秘密</form></body></html>"
    provide_page(reader, tmp_path, monkeypatch, source, "text/html")
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["ok"]
    page = reader.pages[result["data"]["page_id"]]
    assert page.title == "网页测试"
    assert "安装步骤" in page.text
    assert all(
        secret not in page.text for secret in ("脚本秘密", "菜单秘密", "表单秘密")
    )


@pytest.mark.asyncio
async def test_find_is_literal_case_insensitive_and_crosses_display_line_boundaries(
    reader, tmp_path, monkeypatch
):
    text = "a" * 157 + "Needle.*[literal]" + "x" * 200 + "\nNeedle.*[literal]\n最后一行"
    fetch = provide_page(reader, tmp_path, monkeypatch, text)
    event = ReaderEvent()
    result = json.loads(
        await reader.execute(event, "read_url", {"url": "https://example.test"})
    )
    page_id = result["data"]["page_id"]
    first = json.loads(
        await reader.execute(
            event,
            "find_in_page",
            {
                "page_id": page_id,
                "keyword": "needle.*[literal]",
                "max_matches": 1,
            },
        )
    )
    assert first["ok"]
    assert first["data"]["matching_lines_remaining"] == 2
    assert first["data"]["matches"][0]["line"] == 1
    assert first["data"]["matches"][0]["match_end_line"] == 2
    assert first["data"]["has_more"]
    second = json.loads(
        await reader.execute(
            event,
            "find_in_page",
            {
                "page_id": page_id,
                "keyword": "needle.*[literal]",
                "start_line": first["data"]["next_start_line"],
            },
        )
    )
    assert len(second["data"]["matches"]) == 1
    assert not second["data"]["has_more"]
    absent = json.loads(
        await reader.execute(
            event, "find_in_page", {"page_id": page_id, "keyword": ".*not-regex"}
        )
    )
    assert absent["data"]["matches"] == []
    fetch.assert_awaited_once()


@pytest.mark.parametrize(
    "other",
    [
        ReaderEvent(caller="10002"),
        ReaderEvent(session="group-30002"),
        ReaderEvent(platform="platform-b"),
        ReaderEvent(bot="88888"),
    ],
)
@pytest.mark.asyncio
async def test_page_references_are_bound_to_caller_session_platform_and_bot(
    reader, tmp_path, monkeypatch, other
):
    provide_page(reader, tmp_path, monkeypatch, "只允许当前调用者查看的网页正文")
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    params = {"page_id": result["data"]["page_id"]}
    denied = json.loads(await reader.execute(other, "read_page_section", params))
    assert denied["error"]["code"] == "page_unavailable"


@pytest.mark.asyncio
async def test_expiry_eviction_and_refresh_create_distinct_snapshots(
    reader, tmp_path, monkeypatch
):
    reader.config["web_reader"]["max_cached_pages"] = 1
    provide_page(
        reader, tmp_path, monkeypatch, "同一地址再次读取必须产生不同的页面快照"
    )
    event = ReaderEvent()
    first = json.loads(
        await reader.execute(event, "read_url", {"url": "https://example.test"})
    )["data"]["page_id"]
    second = json.loads(
        await reader.execute(event, "read_url", {"url": "https://example.test"})
    )["data"]["page_id"]
    assert first != second
    assert list(reader.pages) == [second]
    reader.pages[second] = replace(reader.pages[second], expires_at=0)
    result = json.loads(
        await reader.execute(event, "read_page_section", {"page_id": second})
    )
    assert result["error"]["code"] == "page_unavailable"
    assert not reader.pages


@pytest.mark.parametrize(
    ("tool", "params"),
    [
        ("read_url", {"url": ""}),
        ("read_url", {"url": 123}),
        ("read_url", {"url": "https://example.test", "extra": True}),
        ("read_url", {"url": "https://example.test\ninvalid"}),
        ("read_page_section", {"page_id": "../file"}),
        ("read_page_section", {"page_id": "a" * 32, "start_line": True}),
        ("read_page_section", {"page_id": "a" * 32, "line_count": 101}),
        ("find_in_page", {"page_id": "a" * 32, "keyword": " "}),
        ("find_in_page", {"page_id": "a" * 32, "keyword": "x", "max_matches": 0}),
    ],
)
@pytest.mark.asyncio
async def test_invalid_tool_arguments_fail_fast(reader, monkeypatch, tool, params):
    fetch = AsyncMock()
    monkeypatch.setattr(reader.runtime, "fetch_url", fetch)
    result = json.loads(await reader.execute(ReaderEvent(), tool, params))
    assert result["error"]["code"] == "invalid_parameters"
    fetch.assert_not_awaited()


@pytest.mark.parametrize(
    ("source", "content_type", "charset", "code"),
    [
        (b"", "text/plain", "utf-8", "content_unavailable"),
        (b"binary\x00data", "text/plain", "utf-8", "unsupported_content_type"),
        (b"hello", "text/plain", "invalid-codec", "invalid_encoding"),
        (b"\xff", "text/plain", "utf-8", "invalid_encoding"),
        (
            b"<html><body><script>render()</script></body></html>",
            "text/html",
            "utf-8",
            "content_unavailable",
        ),
    ],
)
@pytest.mark.asyncio
async def test_unreadable_responses_never_become_successful_snapshots(
    reader, tmp_path, monkeypatch, source, content_type, charset, code
):
    provide_page(reader, tmp_path, monkeypatch, source, content_type, charset)
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["error"]["code"] == code
    assert not reader.pages
    assert not (tmp_path / "downloaded-source").exists()


@pytest.mark.parametrize("charset", ["gb18030", None])
@pytest.mark.asyncio
async def test_chinese_encoding_is_preserved(reader, tmp_path, monkeypatch, charset):
    text = "中文网页内容与安装步骤，不能出现乱码。" * 40
    provide_page(
        reader,
        tmp_path,
        monkeypatch,
        text.encode("gb18030" if charset else "utf-8"),
        charset=charset,
    )
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["ok"]
    assert reader.pages[result["data"]["page_id"]].text == text


@pytest.mark.asyncio
async def test_text_and_output_limits_do_not_silently_truncate(
    reader, tmp_path, monkeypatch
):
    reader.config["web_reader"]["max_text_chars"] = 1000
    provide_page(reader, tmp_path, monkeypatch, "正文" * 501)
    failed = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert failed["error"]["code"] == "content_too_large"
    assert not reader.pages
    reader.config["limits"]["max_output_chars"] = 1000
    provide_page(reader, tmp_path, monkeypatch, '带引号的正文"\\' * 80)
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["ok"] and result["data"]["has_more"]
    assert result["data"]["next_start_line"] == result["data"]["end_line"] + 1


@pytest.mark.asyncio
async def test_disabled_web_reader_blocks_fetch_and_cached_page_access(
    reader, tmp_path, monkeypatch
):
    fetch = provide_page(reader, tmp_path, monkeypatch, "网页正文")
    event = ReaderEvent()
    first = json.loads(
        await reader.execute(event, "read_url", {"url": "https://example.test"})
    )
    assert first["ok"]
    page_id = first["data"]["page_id"]
    reader.config["web_reader"]["enabled"] = False
    reader.config["toolsets"]["enabled_packs"] = ["web"]
    fetch.reset_mock()

    for tool, params in (
        ("read_url", {"url": "https://example.test"}),
        ("read_page_section", {"page_id": page_id}),
        ("find_in_page", {"page_id": page_id, "keyword": "正文"}),
    ):
        result = json.loads(await reader.execute(event, tool, params))
        assert result["ok"] is False
        assert result["error"]["code"] == "capability_unavailable"
        assert "data" not in result
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_pack_and_instance_restrictions_are_enforced_before_fetch(
    reader, monkeypatch
):
    fetch = AsyncMock()
    monkeypatch.setattr(reader.runtime, "fetch_url", fetch)
    reader.config["toolsets"]["disabled_operations"] = ["read_url.read"]
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["error"]["code"] == "capability_unavailable"
    reader.config["toolsets"]["disabled_operations"] = []
    reader.config["platform"]["platform_id"] = "other-platform"
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["error"]["code"] == "permission_denied"
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_parser_keeps_its_capacity_until_the_thread_finishes(
    reader, tmp_path, monkeypatch
):
    reader.slots = asyncio.Semaphore(1)
    provide_page(reader, tmp_path, monkeypatch, "正文")
    entered = threading.Event()
    release = threading.Event()

    def parse(*args):
        entered.set()
        release.wait(10)
        return "title", "解析完成"

    monkeypatch.setattr(reader, "_extract", parse)
    task = asyncio.create_task(
        reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader.slots.locked()
        busy = json.loads(
            await reader.execute(
                ReaderEvent(), "read_url", {"url": "https://example.test"}
            )
        )
        assert busy["error"]["code"] == "busy"
        assert not reader.pages
    finally:
        release.set()
        await reader.close()
    assert not reader.slots.locked()


@pytest_asyncio.fixture
async def local_site():
    started = asyncio.Event()
    release = asyncio.Event()
    requests = []

    async def handle(request):
        requests.append(request.path)
        if request.path == "/plain":
            return web.Response(
                text="本地测试正文，不应带上重定向设置的 Cookie。"
                + str(request.cookies),
                content_type="text/plain",
            )
        if request.path == "/redirect":
            response = web.HTTPFound("/plain")
            response.set_cookie("secret", "must-not-follow")
            raise response
        if request.path == "/loop":
            raise web.HTTPFound("/loop")
        if request.path == "/pdf":
            return web.Response(body=b"%PDF-1.7", content_type="application/pdf")
        if request.path == "/partial":
            return web.Response(
                text="不完整的正文",
                status=206,
                headers={"Content-Range": "bytes 0-10/100"},
            )
        if request.path == "/gzip":
            return web.Response(
                body=gzip.compress(b"a" * (1048576 + 1)),
                headers={"Content-Encoding": "gzip", "Content-Type": "text/plain"},
            )
        if request.path == "/truncated":
            response = web.StreamResponse(
                headers={"Content-Type": "text/plain", "Content-Length": "10000"}
            )
            await response.prepare(request)
            await response.write(b"incomplete")
            request.transport.close()
            return response
        if request.path == "/stream":
            response = web.StreamResponse(headers={"Content-Type": "text/plain"})
            await response.prepare(request)
            await response.write(b"partial body")
            started.set()
            await release.wait()
            return response
        raise web.HTTPForbidden()

    application = web.Application()
    application.router.add_get("/{path:.*}", handle)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    try:
        yield SimpleNamespace(
            base=base, requests=requests, started=started, release=release
        )
    finally:
        release.set()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_default_network_policy_prevents_local_requests(reader, local_site):
    result = json.loads(
        await reader.execute(
            ReaderEvent(), "read_url", {"url": local_site.base + "/plain"}
        )
    )
    assert result["error"]["code"] == "permission_denied"
    assert not local_site.requests


@pytest.mark.asyncio
async def test_shared_transport_validates_redirects_and_does_not_forward_cookies_or_use_proxies(
    reader, local_site, monkeypatch
):
    reader.config["network"]["allow_private_network"] = True
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "")
    validate = AsyncMock(wraps=reader.runtime.validate_url)
    monkeypatch.setattr(reader.runtime, "validate_url", validate)
    result = json.loads(
        await reader.execute(
            ReaderEvent(), "read_url", {"url": local_site.base + "/redirect"}
        )
    )
    assert result["ok"]
    assert result["data"]["url"] == local_site.base + "/plain"
    assert [call.args[0] for call in validate.await_args_list] == [
        local_site.base + "/redirect",
        local_site.base + "/plain",
    ]
    text = reader.pages[result["data"]["page_id"]].text
    assert "must-not-follow" not in text
    assert not list(reader.runtime.temp_dir.glob("url_*"))


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/pdf", "unsupported_content_type"),
        ("/partial", "partial_response"),
        ("/gzip", "invalid_parameters"),
        ("/truncated", "network_error"),
        ("/forbidden", "network_error"),
        ("/loop", "network_error"),
    ],
)
@pytest.mark.asyncio
async def test_http_failures_never_leave_snapshots_or_partial_files(
    reader, local_site, path, code
):
    reader.config["network"]["allow_private_network"] = True
    reader.config["web_reader"]["max_download_size_mb"] = 1
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": local_site.base + path})
    )
    assert result["error"]["code"] == code
    assert not reader.pages
    assert not list(reader.runtime.temp_dir.glob("url_*"))


@pytest.mark.asyncio
async def test_redirect_destination_is_rejected_before_connecting(
    reader, local_site, monkeypatch
):
    reader.config["network"]["allow_private_network"] = True
    validation = AsyncMock(
        side_effect=[None, QQToolError("permission_denied", "禁止访问重定向目标")]
    )
    monkeypatch.setattr(reader.runtime, "validate_url", validation)
    result = json.loads(
        await reader.execute(
            ReaderEvent(), "read_url", {"url": local_site.base + "/redirect"}
        )
    )
    assert result["error"]["code"] == "permission_denied"
    assert local_site.requests == ["/redirect"]


@pytest.mark.asyncio
async def test_shutdown_cancels_stream_download_and_removes_partial_file(
    reader, local_site
):
    reader.config["network"]["allow_private_network"] = True
    task = asyncio.create_task(
        reader.execute(ReaderEvent(), "read_url", {"url": local_site.base + "/stream"})
    )
    await asyncio.wait_for(local_site.started.wait(), 5)
    await reader.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not reader.pages
    assert not list(reader.runtime.temp_dir.glob("url_*"))
    assert not reader.slots.locked()


@pytest.mark.asyncio
async def test_connection_resolver_rejects_dns_rebinding(reader, monkeypatch):
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    resolver = AsyncMock(side_effect=[public, private])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolver)
    result = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert result["error"]["code"] == "network_error"
    assert resolver.await_count == 2
    assert not reader.pages


@pytest.mark.asyncio
async def test_resolver_rejects_a_mixed_public_private_dns_response(monkeypatch):
    responses = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 443, 0, 0)),
    ]
    monkeypatch.setattr(
        asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=responses)
    )
    with pytest.raises(OSError, match="globally routable"):
        await _ValidatedResolver(False).resolve("example.test", 443)


@pytest.mark.asyncio
async def test_media_download_still_registers_owned_file_through_shared_transport(
    reader, local_site
):
    reader.config["network"]["allow_private_network"] = True
    path = await reader.runtime.download_url(local_site.base + "/plain", "10001")
    assert path.is_file()
    call = reader.runtime.storage.add_media_ref.await_args
    assert call.args[1] == "10001"
    assert call.args[3] == path


@pytest.mark.asyncio
async def test_web_tool_handlers_and_debounce_hook_use_the_existing_plugin(
    reader, tmp_path, monkeypatch
):
    provide_page(reader, tmp_path, monkeypatch, "第一段正文\n第二段安装说明")
    plugin = object.__new__(QQEnhancePlugin)
    plugin.web_reader = reader
    plugin.debouncer = SimpleNamespace(protect=Mock())
    event = ReaderEvent()
    first = json.loads(await plugin.read_url(event, "https://example.test"))
    page_id = first["data"]["page_id"]
    section = json.loads(await plugin.read_page_section(event, page_id, 2, 1))
    assert section["data"]["lines"] == [{"line": 2, "text": "第二段安装说明"}]
    found = json.loads(await plugin.find_in_page(event, page_id, "安装"))
    assert found["data"]["matches"][0]["line"] == 2
    await plugin.protect_debounce_tool(
        event, SimpleNamespace(name="read_url"), {"url": "https://example.test"}
    )
    plugin.debouncer.protect.assert_called_once_with(event)


@pytest.mark.asyncio
async def test_oversized_snapshot_does_not_evict_an_existing_page(
    reader, tmp_path, monkeypatch
):
    reader.config["web_reader"]["max_cache_mb"] = 1
    provide_page(reader, tmp_path, monkeypatch, "原来的正常快照")
    original = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    page_id = original["data"]["page_id"]
    provide_page(reader, tmp_path, monkeypatch, "行\n" * 30000)
    refused = json.loads(
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    )
    assert refused["error"]["code"] == "cache_limit"
    assert list(reader.pages) == [page_id]


@pytest.mark.asyncio
async def test_audit_failure_discards_a_new_snapshot(reader, tmp_path, monkeypatch):
    provide_page(
        reader, tmp_path, monkeypatch, "正文不应在审计失败后留下无法引用的缓存"
    )
    reader.runtime.storage.add_audit.side_effect = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await reader.execute(ReaderEvent(), "read_url", {"url": "https://example.test"})
    assert not reader.pages


@pytest.mark.asyncio
async def test_parser_timeout_does_not_release_capacity_early(
    reader, tmp_path, monkeypatch
):
    reader.config["network"]["timeout_seconds"] = 0.02
    reader.slots = asyncio.Semaphore(1)
    provide_page(reader, tmp_path, monkeypatch, "正文")
    release = threading.Event()

    def parse(*args):
        release.wait(5)
        return "title", "迟到的解析结果"

    monkeypatch.setattr(reader, "_extract", parse)
    try:
        result = json.loads(
            await reader.execute(
                ReaderEvent(), "read_url", {"url": "https://example.test"}
            )
        )
        assert result["error"]["code"] == "timeout"
        assert reader.slots.locked()
        assert not reader.pages
    finally:
        release.set()
        await reader.close()


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "https://user:password@example.test",
        "http://example.test:invalid",
    ],
)
@pytest.mark.asyncio
async def test_bad_url_scheme_credentials_and_port_fail_before_dns(
    reader, monkeypatch, url
):
    resolve = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    result = json.loads(await reader.execute(ReaderEvent(), "read_url", {"url": url}))
    assert result["error"]["code"] == "invalid_parameters"
    resolve.assert_not_awaited()
