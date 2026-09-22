from __future__ import annotations

from django.db import migrations


class MySQLOnlyRunSQL(migrations.RunSQL):
    """
    RunSQL that executes only on MySQL. Used for FULLTEXT indexes, which
    other backends (e.g. SQLite in local test runs) do not support. On those
    backends ListingQuerySet.search() falls back to icontains.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)
