from rest_framework import status
from rest_framework.views import exception_handler as drf_exception_handler

from core.utils.api_response import error_response


def custom_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    request = context.get("request")

    if response is None:
        return error_response(
            request,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred.",
            error="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    code = "REQUEST_FAILED"
    message = "Request failed."
    if response.status_code == status.HTTP_400_BAD_REQUEST:
        code = "VALIDATION_ERROR"
        message = "Validation failed."
    elif response.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "UNAUTHORIZED"
        message = "Authentication credentials were invalid."
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        code = "FORBIDDEN"
        message = "You do not have permission to perform this action."
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
        message = "Requested resource not found."

    return error_response(
        request,
        code=code,
        message=message,
        error=response.data,
        status_code=response.status_code,
    )
