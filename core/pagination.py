from __future__ import annotations

from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """
    Default pagination. The page size is client-controlled but capped,
    otherwise a single request could dump the whole table.
    """

    page_size_query_param = "page_size"
    max_page_size = 100
