from django.urls import path

from . import views

urlpatterns = [
    # GET /api/v1/dashboard/summary/
    path("summary/", views.DashboardSummaryView.as_view(), name="dashboard-summary"),

    # GET /api/v1/dashboard/jobcard-funnel/
    path("jobcard-funnel/", views.JobCardFunnelView.as_view(), name="dashboard-jobcard-funnel"),

    # GET /api/v1/dashboard/revenue-trend/?months=6
    path("revenue-trend/", views.RevenueTrendView.as_view(), name="dashboard-revenue-trend"),

    # GET /api/v1/dashboard/payment-distribution/
    path("payment-distribution/", views.PaymentDistributionView.as_view(), name="dashboard-payment-distribution"),

    # GET /api/v1/dashboard/recent-activity/?limit=10
    path("recent-activity/", views.RecentActivityView.as_view(), name="dashboard-recent-activity"),

    # GET /api/v1/dashboard/top-services/?limit=5&months=3
    path("top-services/", views.TopServicesView.as_view(), name="dashboard-top-services"),
]
