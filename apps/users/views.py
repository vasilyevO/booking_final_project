from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import User
from .serializers import RegisterSerializer, UserSerializer
from django.utils.translation import gettext_lazy as _


class UserViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    RU: Пользователи. Списка нет намеренно: перечень всех аккаунтов —
        утечка персональных данных, для проекта он не нужен.
    EN: Users. There is deliberately no list endpoint: enumerating all accounts
        leaks personal data and the project does not need it.
    """

    queryset = User.objects.all()
    serializer_class = UserSerializer
    lookup_field = "public_id"
    permission_classes = [IsAuthenticated]

    @extend_schema(summary=_("Register a new account"), request=RegisterSerializer)
    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def register(self, request):
        """
        RU: Регистрация. Единственный эндпоинт, открытый анонимам.
        EN: Registration. The only endpoint open to anonymous users.
        """
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary=_("Current user profile"))
    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        """
        RU: Свой профиль. Отдельный эндпоинт, чтобы клиенту не нужно было
            знать собственный public_id.
        EN: The caller's own profile. A dedicated endpoint so the client does
            not need to know its own public_id.
        """
        if request.method == "PATCH":
            serializer = UserSerializer(request.user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
        return Response(UserSerializer(request.user).data)