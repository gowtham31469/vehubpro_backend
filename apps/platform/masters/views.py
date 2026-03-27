from rest_framework import status
from rest_framework.views import APIView

from apps.platform.customers.permissions import IsAuthenticatedCustomerAccess
from apps.platform.masters.models import City, State
from apps.platform.masters.serializers import CitySerializer, StateSerializer
from core.utils.api_response import success_response


class StateListAPIView(APIView):
    permission_classes = [IsAuthenticatedCustomerAccess]

    def get(self, request):
        queryset = State.objects.all().order_by("name")
        serializer = StateSerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="States retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )


class CityListAPIView(APIView):
    permission_classes = [IsAuthenticatedCustomerAccess]

    def get(self, request):
        state_id = request.query_params.get("state_id")
        queryset = City.objects.select_related("state").all().order_by("name")
        if state_id:
            queryset = queryset.filter(state_id=state_id)
        serializer = CitySerializer(queryset, many=True)
        return success_response(
            request,
            code="DATA_RETRIEVED",
            message="Cities retrieved successfully.",
            data=serializer.data,
            status_code=status.HTTP_200_OK,
        )
