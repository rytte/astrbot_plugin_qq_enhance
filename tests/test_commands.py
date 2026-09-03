from __future__ import annotations

from astrbot_plugin_qq_extension_tools.main import _format_audit_rows


def test_format_audit_rows_is_human_readable() -> None:
    text = _format_audit_rows(
        [
            {
                "created_at": 0,
                "operation_id": "qq_group_manage.leave",
                "caller_id": "10001",
                "target_kind": "group",
                "target_id": "30001",
                "risk": "destructive",
                "decision": "confirmed",
                "result_code": "ok",
                "pending_id": "a8ec404e",
                "duration_ms": 247,
            }
        ]
    )

    assert text.startswith("最近 1 条审计记录：")
    assert "1970-01-01" in text
    assert "操作：qq_group_manage.leave" in text
    assert "调用者：10001" in text
    assert "目标：群 30001" in text
    assert "风险：破坏性（destructive）" in text
    assert "决策：已确认（confirmed）" in text
    assert "结果：成功（ok）" in text
    assert "耗时：247 ms" in text
    assert "确认 ID：a8ec404e" in text


def test_format_audit_rows_handles_empty_results() -> None:
    assert _format_audit_rows([]) == "暂无审计记录。"
