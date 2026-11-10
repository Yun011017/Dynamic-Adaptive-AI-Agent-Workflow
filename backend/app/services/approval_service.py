from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import ApprovalRequest, ExecutionAction

class ApprovalService:
    @staticmethod
    def submit_for_review(db: Session, *, action: ExecutionAction, requested_by: str = "admin") -> ApprovalRequest:
        if action.status != "DRAFT":
            raise HTTPException(409, f"Action in status {action.status} cannot be submitted for review")

        scheduled_at = action.payload.get("scheduled_at")
        if not scheduled_at:
            raise HTTPException(422, "送審前請設定未來的預計發布時間")
        try:
            publish_at = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(422, "預計發布時間格式不正確") from exc
        if publish_at <= datetime.now(timezone.utc):
            raise HTTPException(422, "預計發布時間必須晚於目前時間")
        if not action.payload.get("meta_adapter_payload"):
            raise HTTPException(422, "送審前請補齊公開 HTTPS 圖片網址")
        
        # 標記 action 為 PENDING_REVIEW
        action.status = "PENDING_REVIEW"
        
        expires_at = datetime.now(timezone.utc) + timedelta(hours=72)
        approval = ApprovalRequest(
            workspace_id=action.workspace_id,
            action_id=action.id,
            draft_version=action.draft_version,
            content_hash=action.content_hash,
            status="PENDING_REVIEW",
            requested_by=requested_by,
            expires_at=expires_at,
        )
        db.add(approval)
        db.flush()
        return approval

    @staticmethod
    def process_decision(
        db: Session,
        *,
        approval: ApprovalRequest,
        action: ExecutionAction,
        decision: str,
        reason: str | None,
        reviewer: str = "admin",
    ) -> ApprovalRequest:
        if approval.status != "PENDING_REVIEW":
            raise HTTPException(409, f"Approval request is already in status {approval.status}")
        
        now = datetime.now(timezone.utc)
        approval.reviewed_by = reviewer
        approval.decided_at = now
        approval.decision_reason = reason

        if decision == "approved":
            approval.status = "APPROVED"
            scheduled_at = datetime.fromisoformat(
                str(action.payload["scheduled_at"]).replace("Z", "+00:00")
            )
            # 核准要覆蓋到發布時間，否則已經審核完成的未來排程會在
            # worker 執行前失效。
            approval.expires_at = max(
                now + timedelta(hours=24),
                scheduled_at + timedelta(hours=1),
            )
            # 排程資料已在送審前確認；核准後才正式進入全站排程佇列。
            action.status = "SCHEDULED"
        elif decision == "rejected":
            approval.status = "REJECTED"
            action.status = "REJECTED"
        elif decision == "needs_revision":
            approval.status = "REJECTED"
            # 退回修改必須回到同一份 Strategy 的提案清單，讓使用者直接
            # 修正後重新送審；SUPERSEDED 只保留給真正被新版本取代的草稿。
            action.status = "DRAFT"
        else:
            raise HTTPException(422, "Invalid decision")
        
        db.flush()
        return approval

    @staticmethod
    def verify_publish_preconditions(
        approval: ApprovalRequest | None,
        action: ExecutionAction,
        oauth_valid: bool = True
    ) -> None:
        """依照規格書第 7.1 節發布前嚴格檢查"""
        if not approval or approval.status != "APPROVED":
            raise HTTPException(
                status_code=403,
                detail={"error": "PUBLISH_REJECTED_NO_APPROVAL", "message": "此操作未經核准，拒絕發布！"}
            )
        
        now = datetime.now(timezone.utc)
        if approval.expires_at and approval.expires_at < now:
            raise HTTPException(
                status_code=403,
                detail={"error": "APPROVAL_EXPIRED", "message": "核准已逾期，請重新送審！"}
            )

        if approval.content_hash != action.content_hash:
            raise HTTPException(
                status_code=409,
                detail={"error": "CONTENT_HASH_MISMATCH", "message": "內容已被竄改，與審核時之雜湊不符！"}
            )

        if action.status == "SUPERSEDED":
            raise HTTPException(
                status_code=409,
                detail={"error": "ACTION_SUPERSEDED", "message": "此版本已被新版取代，不得發布！"}
            )

        if not oauth_valid:
            raise HTTPException(
                status_code=401,
                detail={"error": "OAUTH_UNAUTHORIZED", "message": "外部帳號授權失效或未配置！"}
            )
