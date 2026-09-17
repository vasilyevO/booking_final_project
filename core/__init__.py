# RU: без этого Django возьмёт базовый AppConfig и ready() не выполнится
# EN: without this Django uses the base AppConfig and ready() never runs
default_app_config = "core.apps.CoreConfig"