from unittest.mock import patch

from django.test import RequestFactory, TestCase

from core.audit.constants import AuditAction, AuditModule
from core.audit.middleware import AuditMiddleware
from core.audit.service import log_audit_event


class AuditTests(TestCase):
    @patch("core.audit.service.logger")
    def test_log_audit_event_masks_sensitive_headers(self, mock_logger):
        log_audit_event(
            actor_id="user-1",
            actor_type="user",
            action=AuditAction.LOGIN,
            module=AuditModule.AUTH,
            ip_address="127.0.0.1",
            method="POST",
            endpoint="/api/v1/auth/login/",
            headers={"authorization": "Bearer abc", "email": "user@example.com"},
        )
        call = mock_logger.info.call_args
        payload = call.kwargs["extra"]["event"]
        self.assertEqual(payload["headers"]["authorization"], "***")
        self.assertNotEqual(payload["headers"]["email"], "user@example.com")

    @patch("core.audit.middleware.log_audit_event")
    def test_audit_middleware_captures_mutating_api(self, mock_audit):
        request = RequestFactory().post("/api/v1/auth/login/", data={})
        request.user = type("Anonymous", (), {"is_authenticated": False})()
        middleware = AuditMiddleware(lambda req: type("Response", (), {"status_code": 200})())
        middleware(request)
        self.assertTrue(mock_audit.called)
