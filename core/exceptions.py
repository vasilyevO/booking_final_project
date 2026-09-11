from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    """
    RU: Переводит ValidationError уровня модели в формат ответа DRF.
        Без этого full_clean() в save() даст клиенту 500 вместо 400.
    EN: Translates a model-level ValidationError into the DRF response format.
        Without it, full_clean() inside save() returns 500 instead of 400.
    """
    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        exc = DRFValidationError(detail=detail)
    return drf_exception_handler(exc, context)