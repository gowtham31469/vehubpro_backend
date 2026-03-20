from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.logging.utils import CorrelationIdMiddleware, mask_sensitive_data
from core.middleware.request_logging import RequestLoggingMiddleware


class LoggingUtilityTests(TestCase):
    def test_mask_sensitive_data(self):
        payload = {
            "email": "user@example.com",
            "phone": "+919876543210",
            "password": "plaintext",
            "token": "abc123xyz890",
            "nested": {"authorization": "Bearer token"},
        }
        masked = mask_sensitive_data(payload)
        self.assertNotEqual(masked["email"], payload["email"])
        self.assertNotEqual(masked["phone"], payload["phone"])
        self.assertEqual(masked["password"], "***")
        self.assertEqual(masked["token"], "***")
        self.assertEqual(masked["nested"]["authorization"], "***")

    def test_correlation_id_middleware_sets_header(self):
        request = RequestFactory().get("/health")
        middleware = CorrelationIdMiddleware(lambda req: HttpResponse("ok"))
        response = middleware(request)
        self.assertIn("X-Request-ID", response)

    def test_request_logging_middleware_logs_event(self):
        request = RequestFactory().post("/api/v1/auth/login/", data={"email": "a@b.com"})
        middleware = RequestLoggingMiddleware(lambda req: HttpResponse("ok", status=200))
        with self.assertLogs("core.middleware.request_logging", level="INFO") as captured:
            middleware(request)
        self.assertTrue(any("request_completed" in entry for entry in captured.output))
