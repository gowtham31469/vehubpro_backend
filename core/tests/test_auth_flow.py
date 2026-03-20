from django.contrib.auth.hashers import make_password
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.encryption.pii import encryptor
from apps.platform.masters.models import Role
from apps.platform.users.models import User, UserPII


class AuthFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.role = Role.objects.create(code="SUPER_ADMIN", name="Super Admin")
        self.user = User.objects.create(
            password=make_password("123456789"),
            is_superuser=True,
            status="active",
            role=self.role,
            is_staff=True,
            is_active=True,
        )
        email = "gowthamkumar1394@gmail.com"
        email_enc, email_ver = encryptor.encrypt(email)
        name_enc, name_ver = encryptor.encrypt("Gowtham")
        UserPII.objects.create(
            user=self.user,
            email_hash=encryptor.hash_value(email),
            email_encrypted=email_enc,
            email_key_version=email_ver,
            full_name_encrypted=name_enc,
            full_name_key_version=name_ver,
        )

    def test_login_returns_standard_structure(self):
        response = self.client.post(
            "/api/v1/auth/login/",
            {"email": "gowthamkumar1394@gmail.com", "password": "123456789"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertIn("code", body)
        self.assertIn("meta", body)
        self.assertIn("access", body["data"])
        self.assertIn("refresh", body["data"])

    def test_logout_blacklists_refresh_token(self):
        login = self.client.post(
            "/api/v1/auth/login/",
            {"email": "gowthamkumar1394@gmail.com", "password": "123456789"},
            format="json",
        )
        refresh = login.json()["data"]["refresh"]
        response = self.client.post("/api/v1/auth/logout/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
