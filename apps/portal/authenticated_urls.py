from django.urls import path

from apps.portal.views import (
    ChangePasswordAPIView,
    MyVisitRequestsAPIView,
    ProfileAPIView,
    VisitRequestCreateAPIView,
    WishlistItemAPIView,
    WishlistListAPIView,
)

# Customer-JWT-required endpoints — mounted at api/v1/portal/ (see core/urls.py),
# separate from the no-auth api/v1/public/portal/ signup/login routes.
urlpatterns = [
    path("me/profile/", ProfileAPIView.as_view(), name="portal-profile"),
    path("me/change-password/", ChangePasswordAPIView.as_view(), name="portal-change-password"),
    path("me/wishlist/", WishlistListAPIView.as_view(), name="portal-wishlist-list"),
    path("me/wishlist/<uuid:vehicle_id>/", WishlistItemAPIView.as_view(), name="portal-wishlist-item"),
    path("me/visit-requests/", MyVisitRequestsAPIView.as_view(), name="portal-visit-request-list"),
    path(
        "me/vehicles/<uuid:vehicle_id>/book-visit/",
        VisitRequestCreateAPIView.as_view(),
        name="portal-book-visit",
    ),
]
