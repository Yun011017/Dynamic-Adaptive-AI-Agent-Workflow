from fastapi import HTTPException
from typing import Dict, Any
from app.api.schemas.agent_payloads import HumanEvaluation

class ApprovalService:
    @staticmethod
    def calculate_human_evaluation(
        reviewer: str,
        reviewed_at: str,
        deductions: list,
        override_status: str = None
    ) -> HumanEvaluation:
        base_score = 100.0
        total_deduction = sum(d.points for d in deductions)
        final_score = max(0.0, base_score - total_deduction)
        
        # 嚴重事實錯誤 (deduction >= 15 分) 或總分未滿 80 分強制不予通過
        has_critical_error = any(d.points >= 15.0 for d in deductions)
        
        if override_status:
            status = override_status
        elif final_score >= 80.0 and not has_critical_error:
            status = "approved"
        elif final_score >= 60.0:
            status = "needs_revision"
        else:
            status = "rejected"

        return HumanEvaluation(
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            status=status,
            base_score=base_score,
            total_deduction=total_deduction,
            total_score=final_score,
            deductions=deductions,
            qualitative_notes={
                "has_critical_error": has_critical_error,
                "approved_for_publishing": (status == "approved")
            }
        )

    @staticmethod
    def verify_publish_preconditions(approval_request: Dict[str, Any], action: Dict[str, Any]):
        """依照規格書第 7.1 節檢查發布前置條件"""
        if not approval_request or approval_request.get("status") != "APPROVED":
            raise HTTPException(
                status_code=403,
                detail={"error": "PUBLISH_REJECTED_NO_APPROVAL", "message": "此操作未經核准，拒絕發布！"}
            )
        if approval_request.get("content_hash") != action.get("content_hash"):
            raise HTTPException(
                status_code=409,
                detail={"error": "CONTENT_HASH_MISMATCH", "message": "內容已被竄改，與審核時之雜湊不符！"}
            )