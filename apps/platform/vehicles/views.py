from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType
from apps.platform.vehicles.permissions import IsAuthenticatedVehicleAccess
from apps.platform.vehicles.serializers import (
    FuelTypeSerializer,
    ServiceVehicleSerializer,
    VehicleBrandSerializer,
    VehicleModelSerializer,
    VehicleTypeSerializer,
)
from core.utils.api_response import error_response, success_response
from core.utils.pagination import build_paginated_data


def _is_archive_flag(request):
    value = request.query_params.get("is_archive", request.query_params.get("is_archived", "false"))
    return str(value).strip().lower() in {"true", "1", "yes"}


def _is_active_flag(request):
    value = request.query_params.get("is_active")
    if value is None:
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}


def _tenant_context(request):
    tenant_id = getattr(request.user, "tenant_id", None)
    if not tenant_id:
        return None, error_response(
            request,
            code="TENANT_CONTEXT_MISSING",
            message="Authenticated user is not mapped to a tenant.",
            error="Tenant association is required for this endpoint.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return tenant_id, None


class VehicleTypeListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get(self, request):
        queryset = VehicleType.objects.all().order_by("name")
        serializer = VehicleTypeSerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle types retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = VehicleTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="VEHICLE_TYPE_CREATED",
            message="Vehicle type created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class VehicleTypeDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get_object(self, pk):
        return get_object_or_404(VehicleType, pk=pk)

    def get(self, request, pk):
        serializer = VehicleTypeSerializer(self.get_object(pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle type retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        serializer = VehicleTypeSerializer(self.get_object(pk), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="VEHICLE_TYPE_UPDATED",
            message="Vehicle type updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        serializer = VehicleTypeSerializer(self.get_object(pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="VEHICLE_TYPE_UPDATED",
            message="Vehicle type updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        vehicle_type = self.get_object(pk)
        vehicle_type.delete()
        return success_response(
            request,
            code="VEHICLE_TYPE_DELETED",
            message="Vehicle type deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class FuelTypeListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get(self, request):
        queryset = FuelType.objects.all().order_by("name")
        serializer = FuelTypeSerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Fuel types retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = FuelTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="FUEL_TYPE_CREATED",
            message="Fuel type created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class FuelTypeDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get_object(self, pk):
        return get_object_or_404(FuelType, pk=pk)

    def get(self, request, pk):
        serializer = FuelTypeSerializer(self.get_object(pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Fuel type retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        serializer = FuelTypeSerializer(self.get_object(pk), data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="FUEL_TYPE_UPDATED",
            message="Fuel type updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        serializer = FuelTypeSerializer(self.get_object(pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(
            request,
            code="FUEL_TYPE_UPDATED",
            message="Fuel type updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        fuel_type = self.get_object(pk)
        fuel_type.delete()
        return success_response(
            request,
            code="FUEL_TYPE_DELETED",
            message="Fuel type deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class VehicleBrandListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = VehicleBrand.objects.filter(tenant_id=tenant_id, is_archived=_is_archive_flag(request)).order_by(
            "-created_at"
        )
        is_active = _is_active_flag(request)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle brands retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleBrandSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleBrandSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_BRAND_CREATED",
            message="Vehicle brand created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class VehicleBrandDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(VehicleBrand, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = VehicleBrandSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle brand retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleBrandSerializer(instance, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_BRAND_UPDATED",
            message="Vehicle brand updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleBrandSerializer(
            instance, data=payload, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_BRAND_UPDATED",
            message="Vehicle brand updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        brand = get_object_or_404(VehicleBrand, pk=pk, tenant_id=tenant_id, is_archived=False)
        now = timezone.now()
        VehicleModel.objects.filter(brand_id=brand.id, tenant_id=tenant_id, is_archived=False).update(
            is_archived=True,
            archived_at=now,
            updated_at=now,
        )
        brand.archive()
        return success_response(
            request,
            code="VEHICLE_BRAND_DELETED",
            message="Vehicle brand deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class VehicleModelListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        brand_id = request.query_params.get("brand_id")
        queryset = (
            VehicleModel.objects.select_related("brand", "tenant", "vehicle_type")
            .filter(tenant_id=tenant_id, is_archived=_is_archive_flag(request))
            .order_by("-created_at")
        )
        if brand_id:
            queryset = queryset.filter(brand_id=brand_id, brand__tenant_id=tenant_id)
        is_active = _is_active_flag(request)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active)
            if is_active:
                queryset = queryset.filter(brand__is_active=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle models retrieved successfully.",
            data=build_paginated_data(request, queryset, VehicleModelSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleModelSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_MODEL_CREATED",
            message="Vehicle model created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class VehicleModelDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        return get_object_or_404(VehicleModel, pk=pk, tenant_id=tenant_id)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = VehicleModelSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Vehicle model retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleModelSerializer(instance, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_MODEL_UPDATED",
            message="Vehicle model updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        serializer = VehicleModelSerializer(instance, data=payload, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_MODEL_UPDATED",
            message="Vehicle model updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        vehicle_model = get_object_or_404(VehicleModel, pk=pk, tenant_id=tenant_id, is_archived=False)
        vehicle_model.archive()
        return success_response(
            request,
            code="VEHICLE_MODEL_DELETED",
            message="Vehicle model deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )


class ServiceVehicleListCreateAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        queryset = ServiceVehicle.objects.select_related(
            "tenant", "customer", "vehicle_type", "fuel_type", "brand", "vehicle_model"
        ).filter(
            tenant_id=tenant_id,
            is_archived=_is_archive_flag(request),
        ).order_by("-created_at")
        customer_id = request.query_params.get("customer_id")
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id, customer__tenant_id=tenant_id)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service vehicles retrieved successfully.",
            data=build_paginated_data(request, queryset, ServiceVehicleSerializer),
            status_code=status.HTTP_200_OK,
        )

    def post(self, request):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("tenant_id", None)

        serializer = ServiceVehicleSerializer(data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_CREATED",
            message="Service vehicle created successfully.",
            data=serializer.data,
            status_code=status.HTTP_201_CREATED,
        )


class ServiceVehicleDetailAPIView(APIView):
    permission_classes = [IsAuthenticatedVehicleAccess]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, request, pk):
        tenant_id = getattr(request.user, "tenant_id", None)
        queryset = ServiceVehicle.objects.select_related(
            "tenant", "customer", "vehicle_type", "fuel_type", "brand", "vehicle_model"
        ).filter(
            pk=pk,
            is_archived=_is_archive_flag(request),
        )
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        else:
            queryset = queryset.none()
        return get_object_or_404(queryset)

    def get(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        serializer = ServiceVehicleSerializer(self.get_object(request, pk))
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Service vehicle retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def put(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("tenant_id", None)
        serializer = ServiceVehicleSerializer(instance, data=payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_UPDATED",
            message="Service vehicle updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def patch(self, request, pk):
        tenant_id, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        payload = request.data.copy()
        payload.pop("tenant", None)
        payload.pop("tenant_id", None)
        serializer = ServiceVehicleSerializer(instance, data=payload, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant_id=tenant_id)
        return success_response(
            request,
            code="VEHICLE_UPDATED",
            message="Service vehicle updated successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        _, error = _tenant_context(request)
        if error:
            return error
        instance = self.get_object(request, pk)
        instance.archive()
        return success_response(
            request,
            code="VEHICLE_DELETED",
            message="Service vehicle deleted successfully.",
            data={},
            status_code=status.HTTP_200_OK,
        )
