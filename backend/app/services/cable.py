"""电缆线路业务规则：状态流转、字段校验、绝缘电阻判定与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "cable"
REQUIRED_FIELDS = ["电缆编号", "电缆型号", "起止位置"]
STATUS_ORDER = ["正常运行", "绝缘降低", "待修复", "已修复"]
ACTION_RULES = {"测试绝缘": "正常运行", "标记隐患": "待修复", "安排修复": "已修复"}
NEGATIVE_ACTIONS = []

# 绝缘判定等级，从轻到重；列表与详情共用同一判定入口，保证结论一致
LEVEL_ORDER = ["正常", "关注", "需处理"]

# 绝缘电阻判定规则：按电缆型号 + 起止位置命中，字段为 None 表示通配。
# 多条规则同时命中且条件冲突时按测试日期优先，日期新的规则覆盖日期旧的。
INSULATION_RULES: list[dict[str, Any]] = [
    {
        "电缆型号": None,  # None 表示不限型号
        "起止位置": None,  # None 表示不限起止位置
        "下限": 1.0,  # MΩ，当前测值低于下限判定需处理
        "关注下限": 10.0,  # MΩ，当前测值低于关注下限判定关注
        "变化比例上限": 0.5,  # 较上次测值下降超过 50% 判定需处理
        "关注变化比例": 0.3,  # 较上次测值下降超过 30% 判定关注
        "测试日期": "2026-01-01",
    },
    {
        "电缆型号": "YJV22-8.7/15kV",
        "起止位置": None,
        "下限": 10.0,
        "关注下限": 100.0,
        "变化比例上限": 0.4,
        "关注变化比例": 0.25,
        "测试日期": "2026-09-01",
    },
]

_NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _parse_value(raw: Any) -> float | None:
    """把测值解析成 MΩ 数值；空值或无法解析时返回 None，对应比较直接跳过。"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = _NUMBER_PATTERN.search(str(raw))
    return float(match.group()) if match else None


def _parse_date(raw: Any) -> date:
    """解析测试日期；缺失或格式不对时按最早日期处理，冲突时优先级最低。"""
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return date.min


def _match_rule(entry: dict[str, Any]) -> dict[str, Any] | None:
    """命中适用规则：型号与起止位置都匹配（或通配）的规则里，测试日期最新的优先。"""
    matched = [
        rule
        for rule in INSULATION_RULES
        if (rule["电缆型号"] is None or rule["电缆型号"] == entry.get("电缆型号"))
        and (rule["起止位置"] is None or rule["起止位置"] == entry.get("起止位置"))
    ]
    if not matched:
        return None
    return max(matched, key=lambda rule: _parse_date(rule.get("测试日期")))


def judge_insulation(entry: dict[str, Any]) -> dict[str, str]:
    """对单条电缆段做绝缘判定，返回判定等级与明确结论；列表和详情都走这里。"""
    rule = _match_rule(entry)
    if rule is None:
        return {"绝缘判定": "关注", "判定结论": "未配置适用的判定规则，请补录规则后重新判定"}
    current = _parse_value(entry.get("绝缘电阻"))
    if current is None:
        return {"绝缘判定": "关注", "判定结论": "当前测值缺失，需安排补测后再判定"}

    test_date = str(entry.get("测试日期") or "未登记")
    lower = float(rule["下限"])
    if current < lower:
        return {
            "绝缘判定": "需处理",
            "判定结论": f"{test_date} 测得 {current:g}MΩ，低于下限 {lower:g}MΩ，需立即安排处理",
        }

    level = "正常"
    reasons: list[str] = []
    last = _parse_value(entry.get("上次测值"))
    if last is None or last <= 0:
        compare_note = "上次测值缺失，未参与变化比例比较"
    else:
        compare_note = ""
        drop = (last - current) / last
        ratio_limit = float(rule["变化比例上限"])
        if drop > ratio_limit:
            return {
                "绝缘判定": "需处理",
                "判定结论": (
                    f"{test_date} 测得 {current:g}MΩ，较上次 {last:g}MΩ 下降 {drop:.0%}，"
                    f"超过允许范围 {ratio_limit:.0%}，需立即安排处理"
                ),
            }
        watch_ratio = float(rule["关注变化比例"])
        if drop > watch_ratio:
            level = "关注"
            reasons.append(f"较上次 {last:g}MΩ 下降 {drop:.0%}，超过关注范围 {watch_ratio:.0%}")

    watch_lower = float(rule["关注下限"])
    if current < watch_lower:
        level = "关注"
        reasons.append(f"测值 {current:g}MΩ 低于关注下限 {watch_lower:g}MΩ")

    if level == "正常":
        conclusion = f"{test_date} 测得 {current:g}MΩ，绝缘电阻正常"
    else:
        conclusion = f"{test_date} 判定需关注：{'；'.join(reasons)}"
    if compare_note:
        conclusion = f"{conclusion}（{compare_note}）"
    return {"绝缘判定": level, "判定结论": conclusion}


def _with_judgment(entry: dict[str, Any]) -> dict[str, Any]:
    """在读取结果上附加绝缘判定；不写回存储，避免派生字段污染原始登记数据。"""
    return {**entry, **judge_insulation(entry)}


class CableService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("电缆编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_with_judgment(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return _with_judgment(entry)

    def list_rules(self) -> list[dict[str, Any]]:
        """返回当前生效的绝缘电阻判定规则，便于核对列表与详情用的是同一套口径。"""
        return [dict(rule) for rule in INSULATION_RULES]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ("敷设方式", "绝缘电阻", "上次测值", "测试日期"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return _with_judgment(entry), []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"电缆段 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于电缆线路可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _with_judgment(entry), f"电缆段已{action}"
