"""Deterministic rules for the required labor-rights compliance notice."""

from __future__ import annotations

import re

COMPLIANCE_NOTICE = "具体办理要求可能因地区和实际情况不同，请咨询当地劳动监察部门、劳动争议仲裁机构或法律援助机构。"


class ComplianceRuleService:
    _QUESTION_TERMS = (
        "仲裁时效",
        "仲裁期限",
        "申请仲裁的期限",
        "申请仲裁",
        "申请期限",
        "劳动监察",
        "劳动保障监察",
        "劳动仲裁",
        "仲裁机构",
        "仲裁委员会",
        "法律援助",
        "怎么投诉",
        "如何投诉",
        "去哪投诉",
        "维权流程",
        "维权路径",
        "办理流程",
        "办理路径",
    )
    _ANSWER_PATH_TERMS = (
        "劳动监察部门",
        "劳动保障监察部门",
        "劳动保障监察大队",
        "劳动争议仲裁机构",
        "劳动争议仲裁委员会",
        "法律援助机构",
        "法律援助中心",
        "申请仲裁",
        "提交仲裁申请",
        "投诉至",
        "向劳动监察",
        "到劳动监察",
        "12333",
    )
    _CONCRETE_DEADLINE = re.compile(
        r"(?:\d+|[零〇一二三四五六七八九十百]+)\s*"
        r"(?:个?工作日|日|天|个月|年)\s*(?:内|以内|期限|时效)"
    )
    _DEADLINE_WITH_LEADING_TERM = re.compile(
        r"(?:时效|期限).{0,10}(?:\d+|[零〇一二三四五六七八九十百]+)\s*"
        r"(?:个?工作日|日|天|个月|年)"
    )

    def requires_notice(
        self,
        question: str,
        rewritten_question: str = "",
        final_plan_info: str = "",
    ) -> bool:
        query = f"{question}\n{rewritten_question}"
        plan = f"{final_plan_info}"
        if any(term in query for term in self._QUESTION_TERMS):
            return True
        if any(term in plan for term in self._ANSWER_PATH_TERMS):
            return True
        return bool(
            self._CONCRETE_DEADLINE.search(plan)
            or self._DEADLINE_WITH_LEADING_TERM.search(plan)
        )
