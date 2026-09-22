# without this Django uses the base AppConfig and ready() never runs
default_app_config = "core.apps.CoreConfig"