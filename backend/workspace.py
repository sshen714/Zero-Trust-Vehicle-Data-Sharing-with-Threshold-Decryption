"""Role-specific data and independent approval endpoints."""
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, text
from .dependencies import CurrentUser, DbSession, require_roles
from .models import Role, User, DataRequest

router = APIRouter(prefix='/workspace')
LABELS = {Role.OWNER: ('車主', '提供車輛資料'), Role.VISITOR: ('訪客', '查看交通概況'), Role.VENDOR: ('合作廠商', '分析事故或交通資料'), Role.SUPERVISOR_A: ('主管 A', '審核資料使用目的'), Role.SUPERVISOR_B: ('主管 B', '獨立審核申請'), Role.ADMIN: ('系統管理者', '維護網站與服務')}
LABELS.update({
    Role.RESEARCHER: ('交通研究者', '研究車流、交通行為'),
    Role.POLICE: ('警方', '肇逃、事故案件調查'),
})

def request_view(row):
    state = 'rejected' if 'rejected' in (row.decision_a, row.decision_b) else 'approved' if row.decision_a == row.decision_b == 'approved' else 'pending'
    return dict(id=row.id, vendor_id=row.vendor_id, purpose=row.purpose, decision_a=row.decision_a, decision_b=row.decision_b, status=state, created_at=row.created_at)

def traffic_summary(db):
    total, avg, slow = db.execute(text(
        "SELECT COUNT(*), AVG(speed_kmh), SUM(speed_kmh < 20) FROM raw_trajectories"
    )).one()
    return dict(record_count=total, average_speed_kmh=round(float(avg), 1) if avg is not None else None, slow_record_count=int(slow or 0))


@router.get('')
def workspace(db: DbSession, user: CurrentUser, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    label, task = LABELS[user.role]
    result = dict(role=user.role, role_label=label, task=task)
    if user.role == Role.OWNER:
        result['notice'] = '尚未設定帳號與車輛的對應，目前不提供個別軌跡。'
    elif user.role == Role.VISITOR:
        result['traffic'] = traffic_summary(db)
    elif user.role in (Role.VENDOR, Role.SUPERVISOR_A, Role.SUPERVISOR_B):
        query = select(DataRequest).order_by(DataRequest.id.desc()).limit(100)
        if user.role == Role.VENDOR:
            query = query.where(DataRequest.vendor_id == user.id)
        result['requests'] = [request_view(r) for r in db.scalars(query)]
        if user.role == Role.VENDOR:
            approved = db.scalar(select(DataRequest.id).where(DataRequest.vendor_id == user.id, DataRequest.decision_a == 'approved', DataRequest.decision_b == 'approved').limit(1))
            if approved is not None:
                result['analysis'] = traffic_summary(db)
                result['daily_analysis'] = [dict(date=str(day), record_count=count, average_speed_kmh=round(float(speed), 1) if speed is not None else None) for day, count, speed in db.execute(text(
                    "SELECT DATE(timestamp), COUNT(*), AVG(speed_kmh) FROM raw_trajectories "
                    "GROUP BY DATE(timestamp) ORDER BY DATE(timestamp) DESC LIMIT 30"
                ))]
    elif user.role == Role.ADMIN:
        result['service'] = dict(user_count=db.scalar(select(func.count(User.id))), vehicle_record_count=db.scalar(text("SELECT COUNT(*) FROM raw_trajectories")), request_count=db.scalar(select(func.count(DataRequest.id))))
        result['users'] = [dict(id=u.id, username=u.username, role=u.role, is_active=u.is_active) for u in db.scalars(select(User).order_by(User.id).limit(100))]
    else:
        result['notice'] = '此身份已加入，資料查詢功能尚未實作。'
    return result

class RequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    purpose: str = Field(min_length=10, max_length=500)

class DecisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approved', 'rejected']

@router.post('/requests', status_code=201)
def submit_request(data: RequestInput, db: DbSession, user: Annotated[User, Depends(require_roles(Role.VENDOR))]):
    row = DataRequest(vendor_id=user.id, purpose=data.purpose)
    db.add(row)
    db.commit()
    db.refresh(row)
    return request_view(row)

@router.post('/requests/{request_id}/decision')
def decide(request_id: int, data: DecisionInput, db: DbSession, user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_A, Role.SUPERVISOR_B))]):
    row = db.scalar(select(DataRequest).where(DataRequest.id == request_id).with_for_update())
    if row is None:
        raise HTTPException(404, 'Request not found')
    field, reviewer = ('decision_a', 'reviewer_a') if user.role == Role.SUPERVISOR_A else ('decision_b', 'reviewer_b')
    if getattr(row, field) != 'pending':
        raise HTTPException(409, 'Decision already recorded')
    other_reviewer = row.reviewer_b if user.role == Role.SUPERVISOR_A else row.reviewer_a
    if other_reviewer == user.id:
        raise HTTPException(403, 'Reviewers must be independent')
    setattr(row, field, data.decision)
    setattr(row, reviewer, user.id)
    db.commit()
    db.refresh(row)
    return request_view(row)
