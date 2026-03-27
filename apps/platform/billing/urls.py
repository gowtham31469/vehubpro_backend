from django.urls import path

from apps.platform.billing.views import (
    PlanDetailAPIView,
    PlanListCreateAPIView,
    SubscriptionAddOnDetailAPIView,
    SubscriptionAddOnListCreateAPIView,
    SubscriptionHistoryListAPIView,
    SubscriptionLedgerDetailAPIView,
    SubscriptionLedgerListCreateAPIView,
    TenantSubscriptionDetailAPIView,
    TenantSubscriptionListCreateAPIView,
)

urlpatterns = [
    path("plans/", PlanListCreateAPIView.as_view(), name="plan-list-create"),
    path("plans/<uuid:pk>/", PlanDetailAPIView.as_view(), name="plan-detail"),
    path("subscriptions/", TenantSubscriptionListCreateAPIView.as_view(), name="subscription-list-create"),
    path("subscriptions/<uuid:pk>/", TenantSubscriptionDetailAPIView.as_view(), name="subscription-detail"),
    path("subscriptions/ledger/", SubscriptionLedgerListCreateAPIView.as_view(), name="subscription-ledger-list-create"),
    path("subscriptions/ledger/<uuid:pk>/", SubscriptionLedgerDetailAPIView.as_view(), name="subscription-ledger-detail"),
    path("subscriptions/history/", SubscriptionHistoryListAPIView.as_view(), name="subscription-history-list"),
    path("subscriptions/addons/", SubscriptionAddOnListCreateAPIView.as_view(), name="subscription-addon-list-create"),
    path("subscriptions/addons/<uuid:pk>/", SubscriptionAddOnDetailAPIView.as_view(), name="subscription-addon-detail"),
]
