import pytest

from app.services.compliance import COMPLIANCE_NOTICE, ComplianceRuleService


@pytest.mark.parametrize(
    "question",
    [
        "劳动仲裁时效是多久？",
        "申请仲裁的期限是什么？",
        "我该怎么申请仲裁？",
        "如何向劳动监察部门反映？",
        "劳动仲裁应该去哪里申请？",
        "我可以申请法律援助吗？",
    ],
)
def test_compliance_rules_cover_deadlines_and_rights_paths(question: str) -> None:
    assert ComplianceRuleService().requires_notice(question)


@pytest.mark.parametrize(
    "answer",
    [
        "可以向当地劳动监察部门投诉。",
        "建议提交仲裁申请并向劳动争议仲裁委员会咨询。",
        "应在一年内提出申请。",
        "仲裁时效为一年。",
    ],
)
def test_compliance_rules_detect_concrete_routes_and_deadlines(answer: str) -> None:
    assert ComplianceRuleService().requires_notice(
        "这个结论的依据是什么？", final_plan_info=answer
    )


def test_unrelated_question_and_answer_do_not_require_notice() -> None:
    service = ComplianceRuleService()

    assert not service.requires_notice(
        "试用期工资应该如何计算？",
        final_plan_info="请核对工资记录和劳动合同约定。",
    )
    assert COMPLIANCE_NOTICE.endswith("法律援助机构。")
