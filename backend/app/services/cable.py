"""电缆线路业务规则：状态流转、字段校验与筛选口径都收在这里。

绝缘电阻判定也放在这一层：列表、详情、导出共用同一个判定入口，
保证同一电缆段在任何页面得到的结论一致。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "cable"
RULE_MODULE = "cable_rule"
REQUIRED_FIELDS = ["电缆编号", "电缆型号", "起止位置"]
OPTIONAL_FIELDS = ["敷设方式", "绝缘电阻", "上次测值", "测试日期"]
STATUS_ORDER = ["正常运行", "绝缘降低", "待修复", "已修复"]
ACTION_RULES = {"测试绝缘": "正常运行", "标记隐患": "待修复", "安排修复": "已修复"}
NEGATIVE_ACTIONS = []

# 判定结论三档：正常 / 关注 / 需处理
JUDGE_LEVELS = ["正常", "关注", "需处理"]
# 规则的匹配条件：都填了就要同时命中，只填一个就按一个匹配
RULE_MATCH_FIELDS = ["电缆型号", "起止位置"]
RULE_REQUIRED_FIELDS = ["规则编号", "生效日期", "绝缘下限"]
RULE_NUMERIC_FIELDS = ["绝缘下限", "关注倍数", "变化比例上限", "变化关注比例"]
RULE_DEFAULTS = {"关注倍数": 1.5}


def _parse_number(value: Any) -> float | None:
    """把测值解析成浮点数；空值、占位文本都视为缺失。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("MΩ", "").replace("Ω", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    """解析 YYYY-MM-DD 日期；解析不了就返回 None，由调用方决定兜底。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _rule_matches(rule: dict[str, Any], entry: dict[str, Any]) -> bool:
    """规则上填了的条件必须和电缆段完全一致，没填的条件不参与匹配。"""
    for field in RULE_MATCH_FIELDS:
        expect = str(rule.get(field) or "").strip()
        if expect and expect != str(entry.get(field) or "").strip():
            return False
    return True


def _rule_specificity(rule: dict[str, Any]) -> int:
    """条件填得越多规则越具体，同天生效时优先用更具体的。"""
    return sum(1 for field in RULE_MATCH_FIELDS if str(rule.get(field) or "").strip())


def pick_rule(rules: list[dict[str, Any]], entry: dict[str, Any]) -> dict[str, Any] | None:
    """多条规则命中同一条电缆段时按测试日期优先定夺。

    生效日期不晚于测试日期、且离测试日期最近的规则胜出；
    全都晚于测试日期时取生效最早的一条兜底；电缆段缺测试日期时取最新生效的。
    """
    candidates = [rule for rule in rules if _rule_matches(rule, entry)]
    if not candidates:
        return None
    test_date = _parse_date(entry.get("测试日期"))

    def effective(rule: dict[str, Any]) -> date:
        return _parse_date(rule.get("生效日期")) or date.min

    if test_date is None:
        return max(
            candidates,
            key=lambda rule: (effective(rule), _rule_specificity(rule), str(rule.get("规则编号") or "")),
        )
    on_time = [rule for rule in candidates if effective(rule) <= test_date]
    if on_time:
        return max(
            on_time,
            key=lambda rule: (effective(rule), _rule_specificity(rule), str(rule.get("规则编号") or "")),
        )
    return min(
        candidates,
        key=lambda rule: (effective(rule), -_rule_specificity(rule), str(rule.get("规则编号") or "")),
    )


def judge_entry(entry: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """对单条电缆段给出绝缘电阻判定：正常、关注或需处理。

    低于下限或变化比例超过范围时给出明确结论；缺少上次测值时不参与变化比例比较。
    """
    rule = pick_rule(rules, entry)
    if rule is None:
        return {
            "判定结论": "关注",
            "判定说明": "没有匹配的判定规则，请按电缆型号或起止位置维护阈值",
            "适用规则": "",
            "变化比例": None,
        }
    code = str(rule.get("规则编号") or "")
    current = _parse_number(entry.get("绝缘电阻"))
    if current is None:
        return {
            "判定结论": "关注",
            "判定说明": "当前测值缺失或无法解析，请补测绝缘电阻",
            "适用规则": code,
            "变化比例": None,
        }
    lower = _parse_number(rule.get("绝缘下限"))
    if lower is None or lower <= 0:
        return {
            "判定结论": "关注",
            "判定说明": f"规则{code}缺少有效的绝缘下限，请先修正规则",
            "适用规则": code,
            "变化比例": None,
        }

    last = _parse_number(entry.get("上次测值"))
    ratio: float | None = None
    if last not in (None, 0):
        ratio = round((current - last) / abs(last) * 100, 1)
    missing_last_note = "" if ratio is not None else "；缺少上次测值，未参与变化比例比较"

    def result(level: str, reason: str) -> dict[str, Any]:
        return {"判定结论": level, "判定说明": reason, "适用规则": code, "变化比例": ratio}

    if current < lower:
        return result("需处理", f"绝缘电阻{current:g}MΩ低于下限{lower:g}MΩ{missing_last_note}")

    change_limit = _parse_number(rule.get("变化比例上限"))
    if ratio is not None and change_limit is not None and abs(ratio) > change_limit:
        direction = "上升" if ratio > 0 else "下降"
        return result("需处理", f"较上次测值{direction}{abs(ratio):.1f}%，超出允许变化范围±{change_limit:g}%")

    watch_ratio = _parse_number(rule.get("变化关注比例"))
    if ratio is not None and watch_ratio is not None and abs(ratio) > watch_ratio:
        return result("关注", f"较上次测值变化{ratio:+.1f}%，需持续跟踪")

    watch_factor = _parse_number(rule.get("关注倍数")) or RULE_DEFAULTS["关注倍数"]
    if current < lower * watch_factor:
        return result("关注", f"绝缘电阻{current:g}MΩ接近下限{lower:g}MΩ{missing_last_note}")

    return result("正常", f"绝缘电阻{current:g}MΩ不低于下限{lower:g}MΩ{missing_last_note}")


class CableService:
    def _rules(self) -> list[dict[str, Any]]:
        return store.rows(RULE_MODULE)

    def _enrich(self, entry: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(entry)
        enriched.update(judge_entry(entry, self._rules()))
        return enriched

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
        return [self._enrich(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._enrich(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry.update({field: values.get(field) for field in OPTIONAL_FIELDS if values.get(field) is not None})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

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
        return self._enrich(entry), f"电缆段已{action}"

    def list_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in self._rules()]

    def create_rule(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in RULE_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        if not any(str(values.get(field) or "").strip() for field in RULE_MATCH_FIELDS):
            return None, "电缆型号与起止位置至少填一个，否则规则永远匹配不到电缆段"
        if _parse_date(values.get("生效日期")) is None:
            return None, "生效日期格式应为 YYYY-MM-DD"
        for field in RULE_NUMERIC_FIELDS:
            raw = values.get(field)
            if raw is None or str(raw).strip() == "":
                continue
            if _parse_number(raw) is None:
                return None, f"{field}应为数字"
        lower = _parse_number(values.get("绝缘下限"))
        if lower is None or lower <= 0:
            return None, "绝缘下限应为大于 0 的数字"
        code = str(values.get("规则编号") or "").strip()
        if any(str(rule.get("规则编号") or "") == code for rule in self._rules()):
            return None, f"规则编号「{code}」已存在，请换一个编号"
        rows = self._rules()
        rule: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        rule["规则编号"] = code
        rule["电缆型号"] = str(values.get("电缆型号") or "").strip()
        rule["起止位置"] = str(values.get("起止位置") or "").strip()
        rule["生效日期"] = str(values.get("生效日期") or "").strip()
        rule["绝缘下限"] = lower
        for field in ["关注倍数", "变化比例上限", "变化关注比例"]:
            number = _parse_number(values.get(field))
            if number is not None:
                rule[field] = number
        rule.setdefault("关注倍数", RULE_DEFAULTS["关注倍数"])
        rows.append(rule)
        return rule, ""
