from django.urls import path

from apps.portal.views import CustomerLoginAPIView, CustomerSignupAPIView, CustomerTokenRefreshAPIView

# No-auth signup/login/refresh — mounted at api/v1/public/portal/ (see core/urls.py).
urlpatterns = [
    path("tenants/<str:domain>/signup/", CustomerSignupAPIView.as_view(), name="portal-signup"),
    path("tenants/<str:domain>/login/", CustomerLoginAPIView.as_view(), name="portal-login"),
    path("refresh/", CustomerTokenRefreshAPIView.as_view(), name="portal-refresh"),
]
