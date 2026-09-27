"""电缆线路接口：维护电缆段，覆盖测试绝缘、标记隐患、安排修复等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cable import CableService

router = APIRouter(prefix="/api/cable", tags=["电缆线路"])

service = CableService()

LIST_FIELDS = ["电缆编号", "电缆型号", "起止位置", "敷设方式", "绝缘电阻", "上次测值", "测试日期", "电缆状态", "绝缘判定", "判定结论"]
STATUSES = ["正常运行", "绝缘降低", "待修复", "已修复"]


@router.get("/rules")
def list_rules() -> dict[str, Any]:
    """查看当前生效的绝缘电阻判定规则：型号与起止位置命中规则，冲突时测试日期新的优先。"""
    rules = service.list_rules()
    return {"module": "cable", "total": len(rules), "items": rules}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出电缆线路清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "cable", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按电缆编号检索"),
    status: str | None = Query(default=None, description="正常运行、绝缘降低、待修复、已修复"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按电缆编号与状态过滤电缆线路列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条电缆段明细；与列表共用同一套绝缘判定，不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"电缆段 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条电缆段，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="电缆段已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条电缆段执行测试绝缘、标记隐患、安排修复；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
