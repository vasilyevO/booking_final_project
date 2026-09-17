from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bookings"

    def ready(self) -> None:
        """
        RU: Импорт ради побочного эффекта — регистрации @receiver.
            Без этого метода сигналы не подключатся.
        EN: Imported for the side effect of registering @receiver.
            Without this method the signals are never connected.
        """
        from . import signals