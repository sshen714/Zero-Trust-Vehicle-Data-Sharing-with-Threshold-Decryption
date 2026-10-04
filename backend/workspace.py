"""Role-specific data and independent approval endpoints."""
import csv
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from io import StringIO
from statistics import fmean
from typing import Annotated, Literal
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import delete, select, func
from scripts.decryption import decrypt_location, decrypt_speed
from scripts.encryption import make_plate_lookup
from scripts.pets import apply_owner_pets, apply_researcher_pets
from .database import required_setting
from .mailer import OtpDeliveryError, otp_recipient, send_download_otp
from .dependencies import CurrentUser, DbSession, require_roles
from .models import (
    DataRequest,
    EncryptedTrajectory,
    OtpChallenge,
    Role,
    User,
    Vehicle,
    VehicleOwnership,
)

router = APIRouter(prefix='/workspace')
public_router = APIRouter(prefix='/public')
LABELS = {Role.OWNER: ('車主', '提供車輛資料'), Role.VISITOR: ('訪客', '查看交通概況'), Role.VENDOR: ('合作廠商', '分析事故或交通資料'), Role.SUPERVISOR_A: ('主管 A', '審核資料使用目的'), Role.SUPERVISOR_B: ('主管 B', '獨立審核申請'), Role.ADMIN: ('系統管理者', '維護網站與服務')}
LABELS.update({
    Role.RESEARCHER: ('交通研究者', '研究車流、交通行為'),
    Role.POLICE: ('警方', '肇逃、事故案件調查'),
})

def request_view(row):
    if 'rejected' in (row.decision_a, row.decision_b):
        state = 'rejected'
    elif row.decision_b == 'not_required':
        state = row.decision_a
    elif row.decision_a == 'not_required':
        state = row.decision_b
    else:
        state = 'approved' if row.decision_a == row.decision_b == 'approved' else 'pending'
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


@public_router.get('/traffic-range')
def public_traffic_range(db: DbSession, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    available_start, available_end = db.execute(
        select(
            func.min(EncryptedTrajectory.timestamp),
            func.max(EncryptedTrajectory.timestamp),
        )
    ).one()
    return {
        'start': available_start,
        'end': available_end,
    }


@public_router.get('/average-speed')
def public_average_speed(
    db: DbSession,
    response: Response,
    start: datetime,
    end: datetime,
):
    response.headers['Cache-Control'] = 'no-store'
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    rows = db.execute(
        select(
            EncryptedTrajectory.plate_lookup,
            EncryptedTrajectory.timestamp,
            EncryptedTrajectory.speed_enc,
        )
        .where(
            EncryptedTrajectory.timestamp >= start,
            EncryptedTrajectory.timestamp <= end,
        )
        .order_by(
            EncryptedTrajectory.plate_lookup,
            EncryptedTrajectory.timestamp,
            EncryptedTrajectory.id,
        )
    )
    unique_samples = {}
    for plate_lookup, timestamp, speed_enc in rows:
        unique_samples.setdefault((plate_lookup, timestamp), speed_enc)

    vehicle_speeds = {}
    for (plate_lookup, _), speed_enc in unique_samples.items():
        vehicle_speeds.setdefault(plate_lookup, []).append(
            decrypt_speed(speed_enc)
        )

    # Do not release a statistic that could describe one or two vehicles.
    if len(vehicle_speeds) < 3:
        return {'average_speed_kmh': None}

    per_vehicle_averages = [fmean(speeds) for speeds in vehicle_speeds.values()]
    return {'average_speed_kmh': round(fmean(per_vehicle_averages), 1)}


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
        result['notice'] = '訪客統計已改由不需登入的公開頁面提供。'
    elif user.role in (Role.VENDOR, Role.SUPERVISOR_A, Role.SUPERVISOR_B):
        query = select(DataRequest).order_by(DataRequest.id.desc()).limit(100)
        if user.role == Role.VENDOR:
            query = query.where(DataRequest.vendor_id == user.id)
        result['requests'] = [request_view(r) for r in db.scalars(query)]
        if user.role in (Role.VENDOR, Role.SUPERVISOR_A, Role.SUPERVISOR_B):
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
        if user.role == Role.VENDOR:
            approved = db.scalar(select(DataRequest.id).where(DataRequest.vendor_id == user.id, DataRequest.decision_a == 'approved', DataRequest.decision_b == 'approved').limit(1))
            if approved is not None:
                result['analysis'] = traffic_summary(db)
                result['daily_analysis'] = daily_traffic_analysis(db)
    elif user.role == Role.ADMIN:
        result['service'] = dict(
            member_count=db.scalar(select(func.count(User.id))),
            vehicle_count=db.scalar(select(func.count(Vehicle.vehicle_id))),
            role_count=db.scalar(select(func.count(func.distinct(User.role)))),
        )
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
        result['users'] = [dict(id=u.id, username=u.username, role=u.role, is_active=u.is_active) for u in db.scalars(select(User).order_by(User.id).limit(100))]
    elif user.role == Role.RESEARCHER:
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


def vendor_pet_rng(plate_lookup):
    seed_bytes = hmac.new(
        required_setting('LOCATION_KEY').encode('utf-8'),
        f'vendor-location-pets|{plate_lookup}'.encode('ascii'),
        hashlib.sha256,
    ).digest()
    return np.random.default_rng(int.from_bytes(seed_bytes[:8], 'big'))


def admin_pet_rng(plate_lookup):
    seed_bytes = hmac.new(
        required_setting('LOCATION_KEY').encode('utf-8'),
        f'admin-location-pets|{plate_lookup}'.encode('ascii'),
        hashlib.sha256,
    ).digest()
    return np.random.default_rng(int.from_bytes(seed_bytes[:8], 'big'))


def researcher_pet_rng():
    seed_bytes = hmac.new(
        required_setting('LOCATION_KEY').encode('utf-8'),
        b'researcher-full-pets',
        hashlib.sha256,
    ).digest()
    return np.random.default_rng(int.from_bytes(seed_bytes[:8], 'big'))


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
    rows = list({row.timestamp: row for row in rows}.values())

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

        if protected.empty:
            raise HTTPException(404, 'No trajectories available')

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


def vendor_trajectories(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.VENDOR))],
    plate: Annotated[str, Query(min_length=1, max_length=32)],
    data_type: Literal['location', 'speed'],
    start: datetime,
    end: datetime,
) -> Response:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')

    conditions = [EncryptedTrajectory.plate_lookup == plate_lookup]
    if data_type == 'speed':
        conditions.extend([
            EncryptedTrajectory.timestamp >= start,
            EncryptedTrajectory.timestamp <= end,
        ])
    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(*conditions)
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

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
        rng = vendor_pet_rng(plate_lookup)
        protected = apply_owner_pets(
            pd.DataFrame(location_rows),
            rng=rng,
        ) if location_rows else pd.DataFrame()
        if not protected.empty:
            trip_groups = protected['timestamp'].diff().dt.total_seconds().gt(300).cumsum()
            protected['approximate_latitude'] = protected['lat']
            protected['approximate_longitude'] = protected['lng']
            for _, indexes in protected.groupby(trip_groups, sort=False).groups.items():
                protected.loc[indexes, 'approximate_latitude'] += rng.uniform(-0.0005, 0.0005)
                protected.loc[indexes, 'approximate_longitude'] += rng.uniform(-0.0005, 0.0005)
            protected = protected[
                (protected['timestamp'] >= start)
                & (protected['timestamp'] <= end)
            ]
        if protected.empty:
            raise HTTPException(404, 'No trajectories available')
        writer.writerow(['timestamp', 'approximate_latitude', 'approximate_longitude'])
        for row in protected.itertuples(index=False):
            writer.writerow([
                row.timestamp.isoformat(sep=' '),
                f'{row.approximate_latitude:.6f}',
                f'{row.approximate_longitude:.6f}',
            ])
    else:
        writer.writerow(['timestamp', 'speed_kmh'])
        for row in rows:
            writer.writerow([
                row.timestamp.isoformat(sep=' '),
                f'{decrypt_speed(row.speed_enc):.1f}',
            ])

    filename = f'vendor-{data_type}-trajectories.csv'
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )


def supervisor_a_locations(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_A))],
    plate: Annotated[str, Query(min_length=1, max_length=32)],
    start: datetime,
    end: datetime,
) -> Response:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(
            EncryptedTrajectory.plate_lookup == plate_lookup,
            EncryptedTrajectory.timestamp >= start,
            EncryptedTrajectory.timestamp <= end,
        )
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'latitude', 'longitude'])
    for row in rows:
        location = decrypt_location(row.location_enc)
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f"{location['lat']:.6f}",
            f"{location['lng']:.6f}",
        ])

    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment; filename="supervisor-a-locations.csv"',
        },
    )


def supervisor_b_speeds(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_B))],
    plate: Annotated[str, Query(min_length=1, max_length=32)],
    start: datetime,
    end: datetime,
) -> Response:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(
            EncryptedTrajectory.plate_lookup == plate_lookup,
            EncryptedTrajectory.timestamp >= start,
            EncryptedTrajectory.timestamp <= end,
        )
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'speed_kmh'])
    for row in rows:
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f'{decrypt_speed(row.speed_enc):.1f}',
        ])

    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment; filename="supervisor-b-speeds.csv"',
        },
    )


def admin_trajectories(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    start: datetime,
    end: datetime,
    plate: Annotated[str | None, Query(max_length=32)] = None,
    min_speed: Annotated[float | None, Query(ge=0, le=300)] = None,
    max_speed: Annotated[float | None, Query(ge=0, le=300)] = None,
) -> Response:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    plate = plate.strip() if plate is not None else ''
    has_speed_range = min_speed is not None and max_speed is not None
    if (min_speed is None) != (max_speed is None):
        raise HTTPException(422, 'Both minimum and maximum speed are required')
    if not plate:
        raise HTTPException(422, 'Plate is required')
    if has_speed_range and min_speed > max_speed:
        raise HTTPException(422, 'Minimum speed must not exceed maximum speed')

    conditions = []
    if plate:
        plate_lookup = make_plate_lookup(plate)
        vehicle_exists = db.scalar(
            select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
        )
        if vehicle_exists is None:
            raise HTTPException(404, 'Vehicle is not available')
        conditions.append(EncryptedTrajectory.plate_lookup == plate_lookup)

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(*conditions)
        .order_by(
            EncryptedTrajectory.plate_lookup,
            EncryptedTrajectory.timestamp,
            EncryptedTrajectory.id,
        )
    ))
    rows = list({(row.plate_lookup, row.timestamp): row for row in rows}.values())

    protected_groups = []
    rows_by_vehicle = {}
    for row in rows:
        rows_by_vehicle.setdefault(row.plate_lookup, []).append(row)
    for plate_lookup, vehicle_rows in rows_by_vehicle.items():
        location_rows = []
        for row in vehicle_rows:
            location = decrypt_location(row.location_enc)
            exact_speed = decrypt_speed(row.speed_enc)
            location_rows.append({
                'vehicle_id': plate_lookup,
                'timestamp': row.timestamp,
                'lat': location['lat'],
                'lng': location['lng'],
                'speed_kmh': exact_speed,
                'exact_speed_kmh': exact_speed,
            })
        rng = admin_pet_rng(plate_lookup)
        protected = apply_owner_pets(pd.DataFrame(location_rows), rng=rng)
        if protected.empty:
            continue
        trip_groups = protected['timestamp'].diff().dt.total_seconds().gt(300).cumsum()
        protected['approximate_latitude'] = protected['lat']
        protected['approximate_longitude'] = protected['lng']
        for _, indexes in protected.groupby(trip_groups, sort=False).groups.items():
            protected.loc[indexes, 'approximate_latitude'] += rng.uniform(-0.0005, 0.0005)
            protected.loc[indexes, 'approximate_longitude'] += rng.uniform(-0.0005, 0.0005)
        protected_groups.append(protected)

    protected = (
        pd.concat(protected_groups, ignore_index=True)
        if protected_groups else pd.DataFrame()
    )
    if not protected.empty:
        protected = protected[
            (protected['timestamp'] >= start)
            & (protected['timestamp'] <= end)
        ]
        if has_speed_range:
            protected = protected[
                (protected['exact_speed_kmh'] >= min_speed)
                & (protected['exact_speed_kmh'] <= max_speed)
            ]
        protected = protected.sort_values('timestamp')

    if protected.empty:
        raise HTTPException(404, 'No trajectories available')

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'timestamp',
        'approximate_latitude',
        'approximate_longitude',
        'speed_range_kmh',
    ])
    for row in protected.itertuples(index=False):
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f'{row.approximate_latitude:.6f}',
            f'{row.approximate_longitude:.6f}',
            blurred_range(row.exact_speed_kmh, '10'),
        ])

    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment; filename="admin-trajectories.csv"',
        },
    )


@router.get('/researcher/trajectories')
def researcher_trajectories(
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.RESEARCHER))],
    start: datetime,
    end: datetime,
) -> Response:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')

    rows = list(db.scalars(
        select(EncryptedTrajectory).order_by(
            EncryptedTrajectory.plate_lookup,
            EncryptedTrajectory.timestamp,
            EncryptedTrajectory.id,
        )
    ))
    rows = list({(row.plate_lookup, row.timestamp): row for row in rows}.values())

    decrypted_rows = []
    for row in rows:
        location = decrypt_location(row.location_enc)
        decrypted_rows.append({
            'vehicle_id': row.plate_lookup,
            'timestamp': row.timestamp,
            'lat': location['lat'],
            'lng': location['lng'],
            'speed_kmh': decrypt_speed(row.speed_enc),
        })

    protected = (
        apply_researcher_pets(
            pd.DataFrame(decrypted_rows),
            rng=researcher_pet_rng(),
        )
        if decrypted_rows else pd.DataFrame()
    )
    if not protected.empty:
        protected = protected[
            (protected['timestamp'] >= start)
            & (protected['timestamp'] <= end)
        ].sort_values(['timestamp', 'pseudo_id'])

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'coarsened_timestamp',
        'pseudonym',
        'approximate_latitude',
        'approximate_longitude',
        'approximate_speed_kmh',
    ])
    for row in protected.itertuples(index=False):
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            row.pseudo_id,
            f'{row.lat:.6f}',
            f'{row.lng:.6f}',
            f'{row.speed_kmh:.1f}',
        ])

    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment; filename="researcher-trajectories.csv"',
        },
    )

class VendorLocationRequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    purpose: str = Field(min_length=10, max_length=500)
    plate: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime


class OtpVerificationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    otp: str = Field(pattern=r'^\d{6}$')
    plate: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime


def deliver_otp_and_commit(db, user, otp: str) -> str:
    recipient = otp_recipient(user.role.value, user.email)
    try:
        db.flush()
        send_download_otp(recipient, otp)
    except OtpDeliveryError:
        db.rollback()
        raise HTTPException(503, '驗證碼寄送失敗，請稍後重新申請。') from None
    db.commit()
    return recipient


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def delete_expired_otp_challenges(db, now: datetime) -> None:
    db.execute(
        delete(OtpChallenge).where(OtpChallenge.expires_at <= now)
    )


def otp_digest(
    otp_kind: str,
    request_id: int,
    otp: str,
    plate_lookup: str,
    start: datetime,
    end: datetime,
) -> str:
    scope = '|'.join([
        str(request_id),
        otp,
        plate_lookup,
        start.isoformat(timespec='seconds'),
        end.isoformat(timespec='seconds'),
    ])
    return hmac.new(
        required_setting('JWT_SECRET').encode('utf-8'),
        f'{otp_kind}|{scope}'.encode('ascii'),
        hashlib.sha256,
    ).hexdigest()


class PersonalDownloadRequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    data_type: Literal['location', 'speed', 'trajectories']
    plate: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime
    min_speed: float | None = Field(default=None, ge=0, le=300)
    max_speed: float | None = Field(default=None, ge=0, le=300)


class PersonalDownloadVerificationInput(PersonalDownloadRequestInput):
    otp: str = Field(pattern=r'^\d{6}$')


PERSONAL_DOWNLOAD_TYPES = {
    Role.OWNER: {'location', 'speed'},
    Role.VENDOR: {'location', 'speed'},
    Role.SUPERVISOR_A: {'location'},
    Role.SUPERVISOR_B: {'speed'},
    Role.ADMIN: {'trajectories'},
}


def validate_personal_download_input(data, user):
    if data.data_type not in PERSONAL_DOWNLOAD_TYPES.get(user.role, set()):
        raise HTTPException(403, 'Download type is not available for this role')
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')
    has_min = data.min_speed is not None
    has_max = data.max_speed is not None
    if has_min != has_max:
        raise HTTPException(422, 'Both minimum and maximum speed are required')
    if user.role != Role.ADMIN and (has_min or has_max):
        raise HTTPException(422, 'Speed range is only available to administrators')
    if user.role == Role.ADMIN and has_min and data.min_speed > data.max_speed:
        raise HTTPException(422, 'Minimum speed must not exceed maximum speed')


def personal_download_digest(request_id, otp, user, data):
    scope = json.dumps({
        'request_id': request_id,
        'otp': otp,
        'user_id': user.id,
        'email': user.email,
        'role': user.role.value,
        'data_type': data.data_type,
        'plate_lookup': make_plate_lookup(data.plate),
        'start': data.start.isoformat(),
        'end': data.end.isoformat(),
        'min_speed': data.min_speed,
        'max_speed': data.max_speed,
    }, sort_keys=True, separators=(',', ':'))
    return hmac.new(
        required_setting('JWT_SECRET').encode('utf-8'),
        f'personal-download|{scope}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def validate_personal_download_scope(db, user, data):
    plate_lookup = make_plate_lookup(data.plate)
    if user.role == Role.OWNER:
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
    elif db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    ) is None:
        raise HTTPException(404, 'Vehicle is not available')
    if db.scalar(select(EncryptedTrajectory.id).where(
        EncryptedTrajectory.plate_lookup == plate_lookup,
        EncryptedTrajectory.timestamp >= data.start,
        EncryptedTrajectory.timestamp <= data.end,
    ).limit(1)) is None:
        raise HTTPException(404, 'No trajectories available')


def generate_personal_download(db, user, data):
    if user.role == Role.OWNER:
        return owner_trajectories(
            db, user, data.plate, data.data_type, data.start, data.end,
        )
    if user.role == Role.VENDOR:
        return vendor_trajectories(
            db, user, data.plate, data.data_type, data.start, data.end,
        )
    if user.role == Role.SUPERVISOR_A:
        return supervisor_a_locations(db, user, data.plate, data.start, data.end)
    if user.role == Role.SUPERVISOR_B:
        return supervisor_b_speeds(db, user, data.plate, data.start, data.end)
    if user.role == Role.ADMIN:
        return admin_trajectories(
            db, user, data.start, data.end, data.plate,
            data.min_speed, data.max_speed,
        )
    raise HTTPException(403, 'Personal download OTP is not available for this role')


@router.post('/personal-download-requests', status_code=201)
def submit_personal_download_request(
    data: PersonalDownloadRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(
        Role.OWNER, Role.VENDOR, Role.SUPERVISOR_A,
        Role.SUPERVISOR_B, Role.ADMIN,
    ))],
    response: Response,
):
    validate_personal_download_input(data, user)
    validate_personal_download_scope(db, user, data)
    request_row = DataRequest(
        vendor_id=user.id,
        purpose=f'personal-download:{user.role.value}:{data.data_type}',
        decision_a='not_required',
        decision_b='not_required',
    )
    db.add(request_row)
    db.flush()
    otp = f'{secrets.randbelow(1_000_000):06d}'
    now = utc_now_naive()
    delete_expired_otp_challenges(db, now)
    expires_at = now + timedelta(minutes=5)
    db.add(OtpChallenge(
        request_id=request_row.id,
        otp_hash=personal_download_digest(request_row.id, otp, user, data),
        expires_at=expires_at,
    ))
    recipient = deliver_otp_and_commit(db, user, otp)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return {
        'request_id': request_row.id,
        'expires_at': expires_at,
        'delivery': 'email',
        'recipient_email': recipient,
    }


@router.post('/personal-download-requests/{request_id}/verify-otp')
def verify_personal_download_otp(
    request_id: int,
    data: PersonalDownloadVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(
        Role.OWNER, Role.VENDOR, Role.SUPERVISOR_A,
        Role.SUPERVISOR_B, Role.ADMIN,
    ))],
):
    validate_personal_download_input(data, user)
    request_row = db.scalar(select(DataRequest).where(
        DataRequest.id == request_id,
        DataRequest.vendor_id == user.id,
        DataRequest.purpose == (
            f'personal-download:{user.role.value}:{data.data_type}'
        ),
    ))
    if request_row is None:
        raise HTTPException(404, 'Request not found')
    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.request_id == request_id)
        .order_by(OtpChallenge.id.desc())
        .limit(1)
        .with_for_update()
    )
    if challenge is None:
        raise HTTPException(404, 'OTP challenge not found')
    now = utc_now_naive()
    if now >= challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(410, 'OTP has expired')
    if challenge.attempt_count >= challenge.max_attempts:
        db.delete(challenge)
        db.commit()
        raise HTTPException(429, 'OTP attempt limit reached')
    expected = personal_download_digest(request_id, data.otp, user, data)
    if not hmac.compare_digest(challenge.otp_hash, expected):
        challenge.attempt_count += 1
        exhausted = challenge.attempt_count >= challenge.max_attempts
        if exhausted:
            db.delete(challenge)
        db.commit()
        if exhausted:
            raise HTTPException(429, 'OTP attempt limit reached')
        raise HTTPException(422, 'OTP is incorrect')
    validate_personal_download_scope(db, user, data)
    download = generate_personal_download(db, user, data)
    db.delete(challenge)
    db.commit()
    return download


@router.post('/vendor/location-requests', status_code=201)
def submit_vendor_location_request(
    data: VendorLocationRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.VENDOR))],
    response: Response,
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(data.plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')
    available_start, available_end = db.execute(
        select(
            func.min(EncryptedTrajectory.timestamp),
            func.max(EncryptedTrajectory.timestamp),
        )
    ).one()
    if (
        available_start is None
        or available_end is None
        or data.start < available_start
        or data.end > available_end
    ):
        raise HTTPException(422, 'Requested time is outside the available range')

    request_row = DataRequest(
        vendor_id=user.id,
        purpose=data.purpose,
        decision_a='pending',
        decision_b='not_required',
    )
    db.add(request_row)
    db.flush()

    otp = f'{secrets.randbelow(1_000_000):06d}'
    now = utc_now_naive()
    delete_expired_otp_challenges(db, now)
    expires_at = now + timedelta(minutes=5)
    db.add(OtpChallenge(
        request_id=request_row.id,
        otp_hash=otp_digest(
            'vendor-location-otp',
            request_row.id,
            otp,
            plate_lookup,
            data.start,
            data.end,
        ),
        expires_at=expires_at,
    ))
    recipient = deliver_otp_and_commit(db, user, otp)

    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'

    return {
        'request_id': request_row.id,
        'expires_at': expires_at,
        'delivery': 'email',
        'recipient_email': recipient,
    }


@router.post('/vendor/location-requests/{request_id}/verify-otp')
def verify_vendor_location_otp(
    request_id: int,
    data: OtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.VENDOR))],
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    request_row = db.scalar(
        select(DataRequest).where(
            DataRequest.id == request_id,
            DataRequest.vendor_id == user.id,
        )
    )
    if request_row is None:
        raise HTTPException(404, 'Request not found')

    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.request_id == request_id)
        .order_by(OtpChallenge.id.desc())
        .limit(1)
        .with_for_update()
    )
    if challenge is None:
        raise HTTPException(404, 'OTP challenge not found')
    if challenge.consumed_at is not None:
        db.delete(challenge)
        db.commit()
        raise HTTPException(409, 'OTP has already been used')
    now = utc_now_naive()
    if now >= challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(410, 'OTP has expired')
    if challenge.attempt_count >= challenge.max_attempts:
        db.delete(challenge)
        db.commit()
        raise HTTPException(429, 'OTP attempt limit reached')

    plate_lookup = make_plate_lookup(data.plate)
    expected_hash = otp_digest(
        'vendor-location-otp',
        request_id,
        data.otp,
        plate_lookup,
        data.start,
        data.end,
    )
    if not hmac.compare_digest(challenge.otp_hash, expected_hash):
        challenge.attempt_count += 1
        attempts_exhausted = challenge.attempt_count >= challenge.max_attempts
        if attempts_exhausted:
            db.delete(challenge)
        db.commit()
        if attempts_exhausted:
            raise HTTPException(429, 'OTP attempt limit reached')
        raise HTTPException(422, 'OTP is incorrect')

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(
            EncryptedTrajectory.plate_lookup == plate_lookup,
            EncryptedTrajectory.timestamp >= data.start,
            EncryptedTrajectory.timestamp <= data.end,
        )
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'latitude', 'longitude'])
    for row in rows:
        location = decrypt_location(row.location_enc)
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f"{location['lat']:.6f}",
            f"{location['lng']:.6f}",
        ])

    request_row.decision_a = 'approved'
    db.delete(challenge)
    db.commit()
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': (
                'attachment; filename="vendor-authorized-locations.csv"'
            ),
        },
    )


@router.post('/supervisor-a/speed-requests', status_code=201)
def submit_supervisor_a_speed_request(
    data: VendorLocationRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_A))],
    response: Response,
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(data.plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')
    available_start, available_end = db.execute(
        select(
            func.min(EncryptedTrajectory.timestamp),
            func.max(EncryptedTrajectory.timestamp),
        )
    ).one()
    if (
        available_start is None
        or available_end is None
        or data.start < available_start
        or data.end > available_end
    ):
        raise HTTPException(422, 'Requested time is outside the available range')

    request_row = DataRequest(
        vendor_id=user.id,
        purpose=data.purpose,
        decision_a='not_required',
        decision_b='pending',
    )
    db.add(request_row)
    db.flush()

    otp = f'{secrets.randbelow(1_000_000):06d}'
    now = utc_now_naive()
    delete_expired_otp_challenges(db, now)
    expires_at = now + timedelta(minutes=5)
    db.add(OtpChallenge(
        request_id=request_row.id,
        otp_hash=otp_digest(
            'supervisor-a-speed-otp',
            request_row.id,
            otp,
            plate_lookup,
            data.start,
            data.end,
        ),
        expires_at=expires_at,
    ))
    recipient = deliver_otp_and_commit(db, user, otp)

    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return {
        'request_id': request_row.id,
        'expires_at': expires_at,
        'delivery': 'email',
        'recipient_email': recipient,
    }


@router.post('/supervisor-a/speed-requests/{request_id}/verify-otp')
def verify_supervisor_a_speed_otp(
    request_id: int,
    data: OtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_A))],
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    request_row = db.scalar(
        select(DataRequest).where(
            DataRequest.id == request_id,
            DataRequest.vendor_id == user.id,
            DataRequest.decision_a == 'not_required',
        )
    )
    if request_row is None:
        raise HTTPException(404, 'Request not found')

    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.request_id == request_id)
        .order_by(OtpChallenge.id.desc())
        .limit(1)
        .with_for_update()
    )
    if challenge is None:
        raise HTTPException(404, 'OTP challenge not found')
    if challenge.consumed_at is not None:
        db.delete(challenge)
        db.commit()
        raise HTTPException(409, 'OTP has already been used')
    now = utc_now_naive()
    if now >= challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(410, 'OTP has expired')
    if challenge.attempt_count >= challenge.max_attempts:
        db.delete(challenge)
        db.commit()
        raise HTTPException(429, 'OTP attempt limit reached')

    plate_lookup = make_plate_lookup(data.plate)
    expected_hash = otp_digest(
        'supervisor-a-speed-otp',
        request_id,
        data.otp,
        plate_lookup,
        data.start,
        data.end,
    )
    if not hmac.compare_digest(challenge.otp_hash, expected_hash):
        challenge.attempt_count += 1
        attempts_exhausted = challenge.attempt_count >= challenge.max_attempts
        if attempts_exhausted:
            db.delete(challenge)
        db.commit()
        if attempts_exhausted:
            raise HTTPException(429, 'OTP attempt limit reached')
        raise HTTPException(422, 'OTP is incorrect')

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(
            EncryptedTrajectory.plate_lookup == plate_lookup,
            EncryptedTrajectory.timestamp >= data.start,
            EncryptedTrajectory.timestamp <= data.end,
        )
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'speed_kmh'])
    for row in rows:
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f'{decrypt_speed(row.speed_enc):.1f}',
        ])

    request_row.decision_b = 'approved'
    db.delete(challenge)
    db.commit()
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': (
                'attachment; filename="supervisor-a-authorized-speeds.csv"'
            ),
        },
    )


@router.post('/supervisor-b/location-requests', status_code=201)
def submit_supervisor_b_location_request(
    data: VendorLocationRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_B))],
    response: Response,
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    plate_lookup = make_plate_lookup(data.plate)
    vehicle_exists = db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    )
    if vehicle_exists is None:
        raise HTTPException(404, 'Vehicle is not available')
    available_start, available_end = db.execute(
        select(
            func.min(EncryptedTrajectory.timestamp),
            func.max(EncryptedTrajectory.timestamp),
        )
    ).one()
    if (
        available_start is None
        or available_end is None
        or data.start < available_start
        or data.end > available_end
    ):
        raise HTTPException(422, 'Requested time is outside the available range')

    request_row = DataRequest(
        vendor_id=user.id,
        purpose=data.purpose,
        decision_a='pending',
        decision_b='not_required',
    )
    db.add(request_row)
    db.flush()

    otp = f'{secrets.randbelow(1_000_000):06d}'
    now = utc_now_naive()
    delete_expired_otp_challenges(db, now)
    expires_at = now + timedelta(minutes=5)
    db.add(OtpChallenge(
        request_id=request_row.id,
        otp_hash=otp_digest(
            'supervisor-b-location-otp',
            request_row.id,
            otp,
            plate_lookup,
            data.start,
            data.end,
        ),
        expires_at=expires_at,
    ))
    recipient = deliver_otp_and_commit(db, user, otp)

    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return {
        'request_id': request_row.id,
        'expires_at': expires_at,
        'delivery': 'email',
        'recipient_email': recipient,
    }


@router.post('/supervisor-b/location-requests/{request_id}/verify-otp')
def verify_supervisor_b_location_otp(
    request_id: int,
    data: OtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.SUPERVISOR_B))],
):
    if data.start.tzinfo is not None or data.end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if data.start > data.end:
        raise HTTPException(422, 'Start must not be later than end')

    request_row = db.scalar(
        select(DataRequest).where(
            DataRequest.id == request_id,
            DataRequest.vendor_id == user.id,
            DataRequest.decision_b == 'not_required',
        )
    )
    if request_row is None:
        raise HTTPException(404, 'Request not found')

    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.request_id == request_id)
        .order_by(OtpChallenge.id.desc())
        .limit(1)
        .with_for_update()
    )
    if challenge is None:
        raise HTTPException(404, 'OTP challenge not found')
    if challenge.consumed_at is not None:
        db.delete(challenge)
        db.commit()
        raise HTTPException(409, 'OTP has already been used')
    now = utc_now_naive()
    if now >= challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(410, 'OTP has expired')
    if challenge.attempt_count >= challenge.max_attempts:
        db.delete(challenge)
        db.commit()
        raise HTTPException(429, 'OTP attempt limit reached')

    plate_lookup = make_plate_lookup(data.plate)
    expected_hash = otp_digest(
        'supervisor-b-location-otp',
        request_id,
        data.otp,
        plate_lookup,
        data.start,
        data.end,
    )
    if not hmac.compare_digest(challenge.otp_hash, expected_hash):
        challenge.attempt_count += 1
        attempts_exhausted = challenge.attempt_count >= challenge.max_attempts
        if attempts_exhausted:
            db.delete(challenge)
        db.commit()
        if attempts_exhausted:
            raise HTTPException(429, 'OTP attempt limit reached')
        raise HTTPException(422, 'OTP is incorrect')

    rows = list(db.scalars(
        select(EncryptedTrajectory)
        .where(
            EncryptedTrajectory.plate_lookup == plate_lookup,
            EncryptedTrajectory.timestamp >= data.start,
            EncryptedTrajectory.timestamp <= data.end,
        )
        .order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id)
    ))
    rows = list({row.timestamp: row for row in rows}.values())

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'latitude', 'longitude'])
    for row in rows:
        location = decrypt_location(row.location_enc)
        writer.writerow([
            row.timestamp.isoformat(sep=' '),
            f"{location['lat']:.6f}",
            f"{location['lng']:.6f}",
        ])

    request_row.decision_a = 'approved'
    db.delete(challenge)
    db.commit()
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': (
                'attachment; filename="supervisor-b-authorized-locations.csv"'
            ),
        },
    )

class ScopedOtpRequestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    plate: str = Field(min_length=1, max_length=32)
    start: datetime | None = None
    end: datetime | None = None


class ScopedOtpVerificationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    otp: str = Field(pattern=r'^\d{6}$')
    plate: str = Field(min_length=1, max_length=32)
    start: datetime
    end: datetime


def validate_scoped_otp_times(start: datetime, end: datetime) -> None:
    if start.tzinfo is not None or end.tzinfo is not None:
        raise HTTPException(422, 'Use local timestamps without a timezone offset')
    if start > end:
        raise HTTPException(422, 'Start must not be later than end')


def scoped_otp_digest(actor_kind, data_type, request_id, otp, plate_lookup, start, end):
    # Bind full timestamp precision; verification must not widen the scope
    # within the same second accepted by the older OTP helper.
    namespace = f'{actor_kind}-{data_type}-otp:{start.isoformat()}:{end.isoformat()}'
    return otp_digest(namespace, request_id, otp, plate_lookup or '*', start, end)


def submit_scoped_otp_request(
    actor_kind: Literal['admin', 'police'],
    data_type: Literal['location', 'speed'],
    data: ScopedOtpRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    response: Response,
):
    if (data.start is None) != (data.end is None):
        raise HTTPException(422, 'Provide both start and end')
    plate_lookup = make_plate_lookup(data.plate)
    if db.scalar(
        select(Vehicle.vehicle_id).where(Vehicle.plate_lookup == plate_lookup)
    ) is None:
        raise HTTPException(404, 'Vehicle is not available')
    range_query = select(
        func.min(EncryptedTrajectory.timestamp),
        func.max(EncryptedTrajectory.timestamp),
    )
    range_query = range_query.where(EncryptedTrajectory.plate_lookup == plate_lookup)
    available_start, available_end = db.execute(range_query).one()
    if available_start is None or available_end is None:
        raise HTTPException(404, 'No trajectories available')
    start = data.start if data.start is not None else available_start
    end = data.end if data.end is not None else available_end
    validate_scoped_otp_times(start, end)
    # Explicit time ranges use the same global bounds as the workspace UI.
    global_start, global_end = db.execute(select(
        func.min(EncryptedTrajectory.timestamp), func.max(EncryptedTrajectory.timestamp),
    )).one()
    if start < global_start or end > global_end:
        raise HTTPException(422, 'Requested time is outside the available range')
    if db.scalar(select(EncryptedTrajectory.id).where(
        EncryptedTrajectory.plate_lookup == plate_lookup,
        EncryptedTrajectory.timestamp >= start,
        EncryptedTrajectory.timestamp <= end,
    ).limit(1)) is None:
        raise HTTPException(404, 'No trajectories available')
    request_row = DataRequest(
        vendor_id=user.id,
        purpose=f'{actor_kind}-{data_type}-otp',
        decision_a='pending' if data_type == 'location' else 'not_required',
        decision_b='pending' if data_type == 'speed' else 'not_required',
    )
    db.add(request_row)
    db.flush()
    otp = f'{secrets.randbelow(1_000_000):06d}'
    now = utc_now_naive()
    delete_expired_otp_challenges(db, now)
    expires_at = now + timedelta(minutes=5)
    db.add(OtpChallenge(
        request_id=request_row.id,
        otp_hash=scoped_otp_digest(
            actor_kind, data_type, request_row.id, otp, plate_lookup, start, end,
        ),
        expires_at=expires_at,
    ))
    recipient = deliver_otp_and_commit(db, user, otp)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'no-cache'
    return {
        'request_id': request_row.id,
        'expires_at': expires_at,
        'delivery': 'email',
        'recipient_email': recipient,
        'plate': data.plate,
        'start': start,
        'end': end,
        'data_type': data_type,
    }


def verify_scoped_otp(
    actor_kind: Literal['admin', 'police'],
    data_type: Literal['location', 'speed'],
    request_id: int,
    data: ScopedOtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
):
    validate_scoped_otp_times(data.start, data.end)
    request_row = db.scalar(select(DataRequest).where(
        DataRequest.id == request_id,
        DataRequest.vendor_id == user.id,
        DataRequest.purpose == f'{actor_kind}-{data_type}-otp',
    ))
    if request_row is None:
        raise HTTPException(404, 'Request not found')
    challenge = db.scalar(select(OtpChallenge).where(
        OtpChallenge.request_id == request_id,
    ).order_by(OtpChallenge.id.desc()).limit(1).with_for_update())
    if challenge is None:
        raise HTTPException(404, 'OTP challenge not found')
    if challenge.consumed_at is not None:
        db.delete(challenge)
        db.commit()
        raise HTTPException(409, 'OTP has already been used')
    if utc_now_naive() >= challenge.expires_at:
        db.delete(challenge)
        db.commit()
        raise HTTPException(410, 'OTP has expired')
    if challenge.attempt_count >= challenge.max_attempts:
        db.delete(challenge)
        db.commit()
        raise HTTPException(429, 'OTP attempt limit reached')
    plate_lookup = make_plate_lookup(data.plate)
    expected = scoped_otp_digest(
        actor_kind, data_type, request_id, data.otp,
        plate_lookup, data.start, data.end,
    )
    if not hmac.compare_digest(challenge.otp_hash, expected):
        challenge.attempt_count += 1
        exhausted = challenge.attempt_count >= challenge.max_attempts
        if exhausted:
            db.delete(challenge)
        db.commit()
        if exhausted:
            raise HTTPException(429, 'OTP attempt limit reached')
        raise HTTPException(422, 'OTP is incorrect')
    query = select(EncryptedTrajectory).where(
        EncryptedTrajectory.timestamp >= data.start,
        EncryptedTrajectory.timestamp <= data.end,
    )
    query = query.where(EncryptedTrajectory.plate_lookup == plate_lookup)
    rows = db.scalars(query.order_by(EncryptedTrajectory.timestamp, EncryptedTrajectory.id))
    unique_rows = {(row.plate_lookup, row.timestamp): row for row in rows}
    if not unique_rows:
        raise HTTPException(404, 'No trajectories available')
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['timestamp', 'latitude', 'longitude'] if data_type == 'location'
                    else ['timestamp', 'speed_kmh'])
    for row in unique_rows.values():
        timestamp = row.timestamp.isoformat(sep=' ')
        if data_type == 'location':
            location = decrypt_location(row.location_enc)
            writer.writerow([timestamp, f"{location['lat']:.6f}", f"{location['lng']:.6f}"])
        else:
            writer.writerow([timestamp, f'{decrypt_speed(row.speed_enc):.1f}'])
    if data_type == 'location':
        request_row.decision_a = 'approved'
    else:
        request_row.decision_b = 'approved'
    db.delete(challenge)
    db.commit()
    return Response(
        content='\ufeff' + output.getvalue(),
        media_type='text/csv; charset=utf-8',
        headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': (
                f'attachment; filename="{actor_kind}-authorized-{data_type}.csv"'
            ),
        },
    )


@router.post('/admin/location-requests', status_code=201)
def submit_admin_location_request(
    data: ScopedOtpRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    response: Response,
):
    return submit_scoped_otp_request('admin', 'location', data, db, user, response)


@router.post('/admin/location-requests/{request_id}/verify-otp')
def verify_admin_location_otp(
    request_id: int,
    data: ScopedOtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
):
    return verify_scoped_otp('admin', 'location', request_id, data, db, user)


@router.post('/admin/speed-requests', status_code=201)
def submit_admin_speed_request(
    data: ScopedOtpRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
    response: Response,
):
    return submit_scoped_otp_request('admin', 'speed', data, db, user, response)


@router.post('/admin/speed-requests/{request_id}/verify-otp')
def verify_admin_speed_otp(
    request_id: int,
    data: ScopedOtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.ADMIN))],
):
    return verify_scoped_otp('admin', 'speed', request_id, data, db, user)


@router.post('/police/location-requests', status_code=201)
def submit_police_location_request(
    data: ScopedOtpRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.POLICE))],
    response: Response,
):
    return submit_scoped_otp_request('police', 'location', data, db, user, response)


@router.post('/police/location-requests/{request_id}/verify-otp')
def verify_police_location_otp(
    request_id: int,
    data: ScopedOtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.POLICE))],
):
    return verify_scoped_otp('police', 'location', request_id, data, db, user)


@router.post('/police/speed-requests', status_code=201)
def submit_police_speed_request(
    data: ScopedOtpRequestInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.POLICE))],
    response: Response,
):
    return submit_scoped_otp_request('police', 'speed', data, db, user, response)


@router.post('/police/speed-requests/{request_id}/verify-otp')
def verify_police_speed_otp(
    request_id: int,
    data: ScopedOtpVerificationInput,
    db: DbSession,
    user: Annotated[User, Depends(require_roles(Role.POLICE))],
):
    return verify_scoped_otp('police', 'speed', request_id, data, db, user)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approved', 'rejected']

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
