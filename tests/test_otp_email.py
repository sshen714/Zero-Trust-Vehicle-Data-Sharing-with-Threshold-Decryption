"""Exercise every OTP request family without sending email or touching MySQL."""
import os
import unittest
from datetime import datetime
from unittest.mock import patch
from fastapi import Response, HTTPException
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from backend.database import Base
from backend.models import User, Role, Vehicle, VehicleOwnership, EncryptedTrajectory, DataRequest, OtpChallenge
from backend import workspace as w
from backend.mailer import OtpDeliveryError
from scripts.encryption import make_plate_lookup


class OtpEmailTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://')
        Base.metadata.create_all(self.engine)
        self.db=Session(self.engine)
        self.start=datetime(2026,9,7,8)
        self.end=datetime(2026,9,7,9)
        self.lookup=make_plate_lookup('V00000')
        self.db.add(Vehicle(vehicle_id='internal',plate_lookup=self.lookup))
        for time in [self.start,self.end]:
            self.db.add(EncryptedTrajectory(plate_enc='unused',plate_lookup=self.lookup,timestamp=time,location_enc='unused',speed_enc='unused'))
        self.db.commit()

    def tearDown(self):
        self.db.close();self.engine.dispose()

    def user(self,role):
        user=User(username=role.value,email=f'{role.value}@example.test',hashed_password='unused',role=role,is_active=True)
        self.db.add(user);self.db.flush()
        if role==Role.OWNER:
            self.db.add(VehicleOwnership(owner_id=user.id,vehicle_id='internal'))
        self.db.commit()
        return user

    def assert_mail(self,action,user):
        with patch('backend.workspace.send_download_otp') as send, patch.dict(os.environ, {'OTP_DEFAULT_EMAIL':'','OTP_SUPERVISOR_A_EMAIL':'','OTP_SUPERVISOR_B_EMAIL':''}):
            result=action()
        send.assert_called_once()
        recipient,code=send.call_args.args
        self.assertEqual(recipient,user.email)
        self.assertRegex(code,r'^[0-9]{6}$')
        self.assertNotIn('demo_otp',result)
        self.assertNotIn(code,str(result))
        self.assertEqual(result['delivery'],'email')
        self.assertEqual(result['recipient_email'],user.email)
        challenge=self.db.scalar(select(OtpChallenge).where(OtpChallenge.request_id==result['request_id']))
        self.assertIsNotNone(challenge)
        self.assertNotEqual(challenge.otp_hash,code)
        return result,code

    def test_personal_download_all_roles_and_one_time_verification(self):
        for role,data_type in [(Role.OWNER,'speed'),(Role.VENDOR,'speed'),(Role.SUPERVISOR_A,'location'),(Role.SUPERVISOR_B,'speed'),(Role.ADMIN,'trajectories')]:
            with self.subTest(role=role):
                user=self.user(role)
                payload=dict(plate='V00000',start=self.start,end=self.end,data_type=data_type)
                data=w.PersonalDownloadRequestInput(**payload)
                result,code=self.assert_mail(lambda:w.submit_personal_download_request(data,self.db,user,Response()),user)
                verification=w.PersonalDownloadVerificationInput(**payload,otp=code)
                with patch('backend.workspace.generate_personal_download',return_value=Response('csv')):
                    w.verify_personal_download_otp(result['request_id'],verification,self.db,user)
                self.assertIsNone(self.db.scalar(select(OtpChallenge).where(OtpChallenge.request_id==result['request_id'])))
                with self.assertRaises(HTTPException):
                    w.verify_personal_download_otp(result['request_id'],verification,self.db,user)

    def test_precision_request_families(self):
        data=w.VendorLocationRequestInput(purpose='Research purpose for test',plate='V00000',start=self.start,end=self.end)
        for role,fn in [(Role.VENDOR,w.submit_vendor_location_request),(Role.SUPERVISOR_A,w.submit_supervisor_a_speed_request),(Role.SUPERVISOR_B,w.submit_supervisor_b_location_request)]:
            user=self.user(role)
            self.assert_mail(lambda:fn(data,self.db,user,Response()),user)
        for role in [Role.ADMIN,Role.POLICE]:
            user=self.user(role)
            for kind in ['location','speed']:
                data=w.ScopedOtpRequestInput(plate='V00000',start=self.start,end=self.end)
                self.assert_mail(lambda:w.submit_scoped_otp_request(role.value,kind,data,self.db,user,Response()),user)

    def test_delivery_failure_rolls_back_request_and_code(self):
        user=self.user(Role.VENDOR)
        data=w.PersonalDownloadRequestInput(plate='V00000',start=self.start,end=self.end,data_type='speed')
        with patch('backend.workspace.send_download_otp',side_effect=OtpDeliveryError()):
            with self.assertRaises(HTTPException) as result:
                w.submit_personal_download_request(data,self.db,user,Response())
        self.assertEqual(result.exception.status_code,503)
        for model in [DataRequest,OtpChallenge]:
            self.assertEqual(self.db.scalar(select(func.count()).select_from(model)),0)
