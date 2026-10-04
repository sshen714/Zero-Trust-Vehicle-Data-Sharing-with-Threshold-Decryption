"""Role-specific data and independent approval endpoints."""
import csv
import hashlib
import hmac
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from io import StringIO
from statistics import fmean
from typing import Annotated, Literal
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from scripts.decryption import decrypt_location, decrypt_speed
from scripts.encryption import make_plate_lookup
from scripts.pets import apply_owner_pets
from .database import required_setting
from .dependencies import CurrentUser, DbSession, require_roles
from .models import (
    DataRequest,
    EncryptedTrajectory,
    Role,
    User,
    Vehicle,
    VehicleOwnership,
)

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
    speeds = [
        decrypt_speed(speed_enc)
        for speed_enc in db.scalars(select(EncryptedTrajectory.speed_enc))
    ]
    return dict(
        record_count=len(speeds),
        average_speed_kmh=round(fmean(speeds), 1) if speeds else None,
        slow_record_count=sum(speed < 20 for speed in speeds),
    )


def daily_traffic_analysis(db):
    daily_speeds = {}
    rows = db.execute(select(
        EncryptedTrajectory.timestamp,
        EncryptedTrajectory.speed_enc,
    ))
    for timestamp, speed_enc in rows:
        daily_speeds.setdefault(timestamp.date(), []).append(decrypt_speed(speed_enc))

    return [
        dict(
            date=str(day),
            record_count=len(speeds),
            average_speed_kmh=round(fmean(speeds), 1),
        )
        for day, speeds in sorted(daily_speeds.items(), reverse=True)[:30]
    ]


@router.get('')
def workspace(db: DbSession, user: CurrentUser, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    label, task = LABELS[user.role]
    result = dict(role=user.role, role_label=label, task=task)
    if user.role == Role.OWNER:
        vehicles = db.scalars(
            select(VehicleOwnership.vehicle_id)
            .where(VehicleOwnership.owner_id == user.id)
            .order_by(VehicleOwnership.vehicle_id)
        ).all()
        result['vehicles'] = [dict(vehicle_id=vehicle_id) for vehicle_id in vehicles]
        available_start, available_end = db.execute(
            select(
                func.min(EncryptedTrajectory.timestamp),
                func.max(EncryptedTrajectory.timestamp),
            )
        ).one()
        result['available_time_range'] = (
            dict(start=available_start, end=available_end)
            if available_start is not None and available_end is not None
            else None
        )
        result['notice'] = (
            '請選擇綁定車輛與時間區間，查詢歷史軌跡。'
            if vehicles else '尚未綁定車輛，目前不提供個別軌跡。'
        )
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
                result['daily_analysis'] = daily_traffic_analysis(db)
    elif user.role == Role.ADMIN:
        result['service'] = dict(
            user_count=db.scalar(select(func.count(User.id))),
            vehicle_record_count=db.scalar(
                select(func.count(EncryptedTrajectory.id))
            ),
            request_count=db.scalar(select(func.count(DataRequest.id))),
        )
        result['users'] = [dict(id=u.id, username=u.username, role=u.role, is_active=u.is_active) for u in db.scalars(select(User).order_by(User.id).limit(100))]
    else:
        result['notice'] = '此身份已加入，資料查詢功能尚未實作。'
    return result


def blurred_range(value, step):
    if value is None:
        return None
    step = Decimal(step)
    lower = (Decimal(value) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    return f"{lower:f} 至 {lower + step:f}（不含上限）"


def owner_pet_rng(plate_lookup):
    seed_bytes = hmac.new(
        required_setting('LOCATION_KEY').encode('utf-8'),
        f'owner-location-pets|{plate_lookup}'.encode('ascii'),
        hashlib.sha256,
    ).digest()
    return np.random.default_rng(int.from_bytes(seed_bytes[:8], 'big'))


@router.get('/trajectories')
def owner_trajectories(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.OWNER))],
    plate: Annotated[str, Query(min_length=1, max_length=32)],
    data_type: Literal['location', 'speed'],
    start: datetime | None = None,
    end: datetime | None = None,
) -> Response:
    if (
        (start is not None and start.tzinfo is not None)
        or (end is not None and end.tzinfo is not None)
    ):
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start is not None and end is not None and start > end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(plate)
    binding = db.scalar(
        select(VehicleOwnership.id)
        .join(Vehicle, Vehicle.vehicle_id == VehicleOwnership.vehicle_id)
        .where(
            VehicleOwnership.owner_id == user.id,
            Vehicle.plate_lookup == plate_lookup,
        )
    )
    if binding is None:
        raise HTTPException(403, 'Vehicle is not bound to this account')

    conditions = [EncryptedTrajectory.plate_lookup == plate_lookup]
    if data_type == 'speed' and start is not None:
        conditions.append(EncryptedTrajectory.timestamp >= start)
    if data_type == 'speed' and end is not None:
        conditions.append(EncryptedTrajectory.timestamp <= end)

    rows = list(db.scalars(select(EncryptedTrajectory).where(*conditions).order_by(
        EncryptedTrajectory.timestamp,
        EncryptedTrajectory.id,
    )))

    output = StringIO()
    writer = csv.writer(output)
    if data_type == 'location':
        location_rows = []
        for row in rows:
            location = decrypt_location(row.location_enc)
            location_rows.append({
                'vehicle_id': plate_lookup,
                'timestamp': row.timestamp,
                'lat': location['lat'],
                'lng': location['lng'],
                'speed_kmh': 0,
            })
        rng = owner_pet_rng(plate_lookup)
        protected = apply_owner_pets(
            pd.DataFrame(location_rows),
            rng=rng,
        ) if location_rows else pd.DataFrame()
        if not protected.empty:
            trip_groups = (
                protected['timestamp'].diff().dt.total_seconds().gt(300).cumsum()
            )
            protected['approximate_latitude'] = protected['lat']
            protected['approximate_longitude'] = protected['lng']
            for _, indexes in protected.groupby(trip_groups, sort=False).groups.items():
                latitude_offset = rng.uniform(-0.0005, 0.0005)
                longitude_offset = rng.uniform(-0.0005, 0.0005)
                protected.loc[indexes, 'approximate_latitude'] += latitude_offset
                protected.loc[indexes, 'approximate_longitude'] += longitude_offset
        if start is not None and not protected.empty:
            protected = protected[protected['timestamp'] >= start]
        if end is not None and not protected.empty:
            protected = protected[protected['timestamp'] <= end]

        writer.writerow(['timestamp', 'approximate_latitude', 'approximate_longitude'])
        for row in protected.itertuples(index=False):
            writer.writerow([
                row.timestamp.isoformat(sep=' '),
                f'{row.approximate_latitude:.6f}',
                f'{row.approximate_longitude:.6f}',
            ])
    else:
        writer.writerow(['timestamp', 'speed_range_kmh'])
        for row in rows:
            writer.writerow([
                row.timestamp.isoformat(sep=' '),
                blurred_range(decrypt_speed(row.speed_enc), '10'),
            ])

    filename = f"owner-{data_type}-trajectories.csv"
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )

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
