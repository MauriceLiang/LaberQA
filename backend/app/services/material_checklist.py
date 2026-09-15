"""Structured tool for preparing a labor-dispute material checklist."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.schemas.contracts import (
    MaterialChecklistInput,
    MaterialChecklistOutput,
    ToolExecutionItem,
)

_TOOL_NAME = "generate_rights_material_checklist"
_TOOL_NOTE = "材料清单仅用于信息整理，具体以实际争议和受理机构要求为准。"

_CHECKLISTS: dict[str, list[str]] = {
    "欠薪": [
        "劳动合同或能够证明劳动关系的材料",
        "工资条、银行流水等工资支付记录",
        "考勤、排班或工作记录",
        "与用人单位沟通欠薪问题的记录",
    ],
    "未签劳动合同": [
        "能够证明实际用工关系的材料",
        "工资条、银行流水等工资支付记录",
        "考勤、排班或工作记录",
        "与用人单位沟通劳动合同问题的记录",
    ],
    "解除劳动关系": [
        "劳动合同或能够证明劳动关系的材料",
        "解除通知、离职证明或相关沟通记录",
        "考勤、工资及工作表现记录",
        "与解除理由相关的书面材料或沟通记录",
    ],
}


@tool(
    _TOOL_NAME,
    description="根据劳动争议类型整理通用材料清单，不作法律结论。",
    args_schema=MaterialChecklistInput,
)
def _generate_rights_material_checklist(
    dispute_type: str, description: str
) -> dict[str, Any]:
    """Return a general evidence-organization checklist for a labor dispute."""
    materials = _CHECKLISTS.get(
        dispute_type,
        [
            "劳动合同或能够证明劳动关系的材料",
            "工资、考勤或工作记录",
            "与争议事项相关的通知、书面材料和沟通记录",
        ],
    )
    return {"materials": materials, "note": _TOOL_NOTE}


class ToolDecisionService:
    _MATERIAL_REQUESTS = (
        "什么材料",
        "哪些材料",
        "材料有哪些",
        "需要准备材料",
        "应该准备材料",
        "材料清单",
        "什么证据",
        "哪些证据",
        "证据有哪些",
        "需要什么证据",
        "证据清单",
        "准备证据",
    )

    def decide(
        self, question: str, rewritten_question: str
    ) -> MaterialChecklistInput | None:
        combined = f"{question}\n{rewritten_question}"
        if not any(term in combined for term in self._MATERIAL_REQUESTS):
            return None

        if any(term in combined for term in ("欠薪", "拖欠工资", "工资未发")):
            dispute_type = "欠薪"
        elif any(term in combined for term in ("未签劳动合同", "没有签劳动合同")):
            dispute_type = "未签劳动合同"
        elif any(term in combined for term in ("辞退", "开除", "解除劳动关系")):
            dispute_type = "解除劳动关系"
        else:
            dispute_type = "劳动争议"

        return MaterialChecklistInput(
            dispute_type=dispute_type,
            description=rewritten_question.strip(),
        )


class MaterialChecklistTool:
    def execute(self, payload: MaterialChecklistInput) -> ToolExecutionItem:
        output = _generate_rights_material_checklist.invoke(payload.model_dump())
        return ToolExecutionItem(
            tool_name=_TOOL_NAME,
            input=payload,
            output=MaterialChecklistOutput.model_validate(output),
        )
