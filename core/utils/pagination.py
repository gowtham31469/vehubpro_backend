from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


def build_paginated_data(request, queryset, serializer_class):
    # Opt-in escape hatch for callers that need every row in one response —
    # e.g. a searchable dropdown that filters client-side and can't afford to
    # silently miss records past the 100-row page cap. Everyday paginated
    # list views never send this, so their behavior is unchanged.
    if request.query_params.get("page_size") == "all":
        serializer = serializer_class(queryset, many=True)
        return {
            "count": queryset.count(),
            "next": None,
            "previous": None,
            "results": serializer.data,
        }

    paginator = StandardResultsSetPagination()
    page = paginator.paginate_queryset(queryset, request)
    serializer = serializer_class(page, many=True)
    return {
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": serializer.data,
    }
