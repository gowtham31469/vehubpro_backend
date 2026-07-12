from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView

from apps.platform.billing.models import (
    Plan,
    SubscriptionAddOn,
    SubscriptionHistory,
    SubscriptionLedger,
    TenantSubscription,
)
from apps.platform.billing.permissions import IsSuperAdminRole
from apps.platform.billing.serializers import (
    PlanSerializer,
    SubscriptionAddOnSerializer,
    SubscriptionHistorySerializer,
    SubscriptionLedgerSerializer,
    TenantSubscriptionSerializer,
)
from core.utils.api_response import success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _snapshot_to_history(subscription, change_reason: str) -> None:
    """Copy the current subscription state into SubscriptionHistory before a change."""
    SubscriptionHistory.objects.create(
        tenant=subscription.tenant,
        plan=subscription.plan,
        start_date=subscription.start_date,
        end_date=subscription.end_date,
        billing_cycle=subscription.billing_cycle,
        price=subscription.price,
        max_users=subscription.max_users,
        max_vehicles=subscription.max_vehicles,
        change_reason=change_reason,
    )


def _create_ledger_entry(subscription, event_type: str, user) -> "SubscriptionLedger":
    """Create a ledger entry and link it to the subscription."""
    ledger = SubscriptionLedger.objects.create(
        tenant=subscription.tenant,
        event_type=event_type,
        payload={
            "subscription_id": str(subscription.id),
            "plan_id": str(subscription.plan_id) if subscription.plan_id else None,
            "billing_cycle": subscription.billing_cycle,
            "price": str(subscription.price),
            "status": subscription.status,
            "start_date": str(subscription.start_date),
            "end_date": str(subscription.end_date) if subscription.end_date else None,
            "max_users": subscription.max_users,
            "max_vehicles": subscription.max_vehicles,
        },
        effective_at=timezone.now(),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    subscription.ledger_entry = ledger
    subscription.save(update_fields=["ledger_entry", "updated_at"])
    return ledger


class PlanListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = Plan.objects.filter(is_archived=_is_archive_flag(request)).order_by("name")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Plans retrieved successfully.",
            data=build_paginated_data(request, queryset, PlanSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="PLAN_CREATED",
            message="Plan created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class PlanDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, request, pk):
        return get_object_or_404(Plan, pk=pk, is_archived=_is_archive_flag(request))

    def get(self, request, pk):
        plan = self.get_object(request, pk)
        serializer = PlanSerializer(plan)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Plan retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        plan = self.get_object(request, pk)
        serializer = PlanSerializer(plan, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="PLAN_UPDATED",
            message="Plan updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        plan = self.get_object(request, pk)
        serializer = PlanSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="PLAN_UPDATED",
            message="Plan updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        plan = self.get_object(request, pk)
        plan.archive()
        return success_response(
            request,
            code="PLAN_DELETED",
            message="Plan deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class TenantSubscriptionListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = TenantSubscription.objects.select_related("tenant", "plan", "ledger_entry").filter(
            is_archived=_is_archive_flag(request)
        )
        tenant_id = request.query_params.get("tenant")
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant subscriptions retrieved successfully.",
            data=build_paginated_data(request, queryset, TenantSubscriptionSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = TenantSubscriptionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subscription = serializer.save(ledger_entry=None)

        _create_ledger_entry(subscription, "CONTRACT_STARTED", request.user)

        # Initial history snapshot so the starting state is always recorded
        _snapshot_to_history(subscription, "Initial contract started")

        response_serializer = TenantSubscriptionSerializer(subscription)
        return success_response(
            request,
            code="SUBSCRIPTION_CREATED",
            message="Tenant subscription created successfully.",
            data=response_serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class TenantSubscriptionDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, request, pk):
        return get_object_or_404(TenantSubscription, pk=pk, is_archived=_is_archive_flag(request))

    def get(self, request, pk):
        subscription = self.get_object(request, pk)
        serializer = TenantSubscriptionSerializer(subscription)
        history = SubscriptionHistory.objects.filter(
            tenant=subscription.tenant, is_archived=_is_archive_flag(request)
        ).order_by("-created_at")
        ledger = SubscriptionLedger.objects.filter(
            tenant=subscription.tenant, is_archived=_is_archive_flag(request)
        ).order_by("-effective_at")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Tenant subscription retrieved successfully.",
            data={
                "subscription": serializer.data,
                "history": SubscriptionHistorySerializer(history, many=True).data,
                "ledger": SubscriptionLedgerSerializer(ledger, many=True).data,
            },
            status_code=status.HTTP_200_OK,
        )

    def _update_subscription(self, request, pk, partial=False):
        subscription = self.get_object(request, pk)

        # Determine change reason before we overwrite the fields
        old_plan_id = str(subscription.plan_id) if subscription.plan_id else None
        new_plan_id = str(request.data.get("plan", old_plan_id or ""))
        new_status  = request.data.get("status", subscription.status)

        if new_status == "cancelled":
            event_type    = "CONTRACT_CANCELLED"
            change_reason = "Subscription cancelled"
        elif old_plan_id and new_plan_id and new_plan_id != old_plan_id:
            event_type    = "CONTRACT_RENEWED"
            change_reason = f"Plan changed from {old_plan_id} to {new_plan_id}"
        else:
            event_type    = "CONTRACT_RENEWED"
            change_reason = "Subscription details updated"

        # Snapshot the current state BEFORE applying changes
        _snapshot_to_history(subscription, change_reason)

        serializer = TenantSubscriptionSerializer(subscription, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        # Refresh from DB so ledger payload reflects the saved state
        subscription.refresh_from_db()
        _create_ledger_entry(subscription, event_type, request.user)

        return success_response(
            request,
            code="SUBSCRIPTION_UPDATED",
            message="Tenant subscription updated successfully.",
            data=TenantSubscriptionSerializer(subscription).data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        return self._update_subscription(request, pk, partial=False)

    def patch(self, request, pk):
        return self._update_subscription(request, pk, partial=True)

    def delete(self, request, pk):
        self.get_object(request, pk).archive()
        return success_response(
            request,
            code="SUBSCRIPTION_DELETED",
            message="Tenant subscription deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class SubscriptionLedgerListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = SubscriptionLedger.objects.select_related("tenant", "created_by").filter(
            is_archived=_is_archive_flag(request)
        ).order_by("-effective_at")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Subscription ledger retrieved successfully.",
            data=build_paginated_data(request, queryset, SubscriptionLedgerSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = SubscriptionLedgerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="SUBSCRIPTION_LEDGER_CREATED",
            message="Subscription ledger entry created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class SubscriptionLedgerDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, request, pk):
        return get_object_or_404(SubscriptionLedger, pk=pk, is_archived=_is_archive_flag(request))

    def get(self, request, pk):
        serializer = SubscriptionLedgerSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Subscription ledger entry retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class SubscriptionHistoryListAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = SubscriptionHistory.objects.select_related("tenant", "plan").filter(
            is_archived=_is_archive_flag(request)
        ).order_by("-created_at")
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Subscription history retrieved successfully.",
            data=build_paginated_data(request, queryset, SubscriptionHistorySerializer),
            status_code=status.HTTP_200_OK,
        )


class SubscriptionAddOnListCreateAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get(self, request):
        queryset = SubscriptionAddOn.objects.select_related("subscription", "ledger_entry").filter(
            is_archived=_is_archive_flag(request)
        )
        tenant_id = request.query_params.get("tenant_id")
        if tenant_id:
            queryset = queryset.filter(subscription__tenant_id=tenant_id)
        queryset = queryset.order_by("-created_at")

        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Subscription add-ons retrieved successfully.",
            data=build_paginated_data(request, queryset, SubscriptionAddOnSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = SubscriptionAddOnSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="SUBSCRIPTION_ADDON_CREATED",
            message="Subscription add-on created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class SubscriptionAddOnDetailAPIView(APIView):
    permission_classes = [IsSuperAdminRole]

    def get_object(self, request, pk):
        return get_object_or_404(SubscriptionAddOn, pk=pk, is_archived=_is_archive_flag(request))

    def get(self, request, pk):
        serializer = SubscriptionAddOnSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Subscription add-on retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        addon = self.get_object(request, pk)
        serializer = SubscriptionAddOnSerializer(addon, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="SUBSCRIPTION_ADDON_UPDATED",
            message="Subscription add-on updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        addon = self.get_object(request, pk)
        serializer = SubscriptionAddOnSerializer(addon, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="SUBSCRIPTION_ADDON_UPDATED",
            message="Subscription add-on updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        self.get_object(request, pk).archive()
        return success_response(
            request,
            code="SUBSCRIPTION_ADDON_DELETED",
            message="Subscription add-on deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
