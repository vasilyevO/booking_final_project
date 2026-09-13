from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.analytics.views import AnalyticsViewSet
from apps.bookings.views import BookingViewSet
from apps.listings.views import ListingViewSet
from apps.reviews.views import ReviewViewSet
from apps.users.views import UserViewSet

# RU: DefaultRouter сам строит карту URL и добавляет корневой индекс API.
#     Экшены с @action попадают в неё автоматически.
# EN: DefaultRouter builds the URL map and adds an API root index.
#     @action endpoints are registered automatically.
router = DefaultRouter()
router.register("listings", ListingViewSet, basename="listing")
router.register("bookings", BookingViewSet, basename="booking")
router.register("reviews", ReviewViewSet, basename="review")
router.register("users", UserViewSet, basename="user")
router.register("analytics", AnalyticsViewSet, basename="analytics")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)