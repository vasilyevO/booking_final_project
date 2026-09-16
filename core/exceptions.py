from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_standardized_errors.handler import exception_handler as standardized_handler
from rest_framework.exceptions import ValidationError as DRFValidationError


def custom_exception_handler(exc, context):
    """
    RU: Сначала переводит ValidationError уровня модели в исключение DRF,
        затем отдаёт его стандартизованному форматтеру.
        Порядок обязателен: drf-standardized-errors знает только иерархию
        APIException и вернул бы 500 на исключение Django.
    EN: First translates a model-level ValidationError into a DRF exception,
        then hands it to the standardized formatter.
        The order matters: drf-standardized-errors only understands the
        APIException hierarchy and would return 500 for a Django exception.
    """
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        exc = DRFValidationError(detail=detail)
    return standardized_handler(exc, context)