"""Role-specific data and independent approval endpoints."""
from datetime import datetime
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, Integer
from .dependencies import CurrentUser, DbSession, require_roles
from .models import Role, User, VehicleRecord, DataRequest

router = APIRouter(prefix='/workspace')
LABELS = {Role.OWNER: ('車主', '提供車輛資料'), Role.VISITOR: ('訪客', '查看交通概況'), Role.VENDOR: ('合作廠商', '分析事故或交通資料'), Role.SUPERVISOR_A: ('主管 A', '審核資料使用目的'), Role.SUPERVISOR_B: ('主管 B', '獨立審核申請'), Role.ADMIN: ('系統管理者', '維護網站與服務')}

def request_view(row):
    state = 'rejected' if 'rejected' in (row.decision_a, row.decision_b) else 'approved' if row.decision_a == row.decision_b == 'approved' else 'pending'
    return dict(id=row.id, vendor_id=row.vendor_id, purpose=row.purpose, decision_a=row.decision_a, decision_b=row.decision_b, status=state, created_at=row.created_at)

def traffic_summary(db):
    total, avg, slow, demo = db.execute(select(func.count(VehicleRecord.id), func.avg(VehicleRecord.speed_kmh), func.sum((VehicleRecord.speed_kmh < 20).cast(Integer)), func.sum(VehicleRecord.is_demo.cast(Integer)))).one()
    return dict(record_count=total, average_speed_kmh=round(float(avg), 1) if avg is not None else None, slow_record_count=int(slow or 0), demo_record_count=int(demo or 0))

@router.get('')
def workspace(db: DbSession, user: CurrentUser, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    label, task = LABELS[user.role]
    result = dict(role=user.role, role_label=label, task=task)
    if user.role == Role.OWNER:
        records = db.scalars(select(VehicleRecord).where(VehicleRecord.owner_id == user.id).order_by(VehicleRecord.recorded_at.desc()).limit(100)).all()
        result['records'] = [dict(vehicle_id=r.vehicle_id, recorded_at=r.recorded_at, lat=r.lat, lng=r.lng, speed_kmh=r.speed_kmh, is_demo=r.is_demo) for r in records]
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
                result['daily_analysis'] = [dict(date=str(day), record_count=count, average_speed_kmh=round(float(speed), 1)) for day, count, speed in db.execute(select(func.date(VehicleRecord.recorded_at), func.count(VehicleRecord.id), func.avg(VehicleRecord.speed_kmh)).group_by(func.date(VehicleRecord.recorded_at)).order_by(func.date(VehicleRecord.recorded_at).desc()).limit(30))]
    else:
        result['service'] = dict(user_count=db.scalar(select(func.count(User.id))), vehicle_record_count=db.scalar(select(func.count(VehicleRecord.id))), request_count=db.scalar(select(func.count(DataRequest.id))))
        result['users'] = [dict(id=u.id, username=u.username, role=u.role, is_active=u.is_active) for u in db.scalars(select(User).order_by(User.id).limit(100))]
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


class RecordInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    vehicle_id: str = Field(min_length=1, max_length=32)
    recorded_at: datetime
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)
    speed_kmh: float = Field(ge=0, le=300, allow_inf_nan=False)

@router.post('/records', status_code=201)
def supply_record(data: RecordInput, db: DbSession, user: Annotated[User, Depends(require_roles(Role.OWNER))]):
    row = VehicleRecord(owner_id=user.id, **data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return dict(id=row.id)
