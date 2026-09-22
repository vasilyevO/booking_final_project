from django.db import migrations

from core.db import MySQLOnlyRunSQL


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0002_initial'),
    ]

    operations = [
        MySQLOnlyRunSQL(
            sql="CREATE FULLTEXT INDEX listing_search_ft "
                "ON listings_listing (title, description);",
            reverse_sql="DROP INDEX listing_search_ft ON listings_listing;",
        ),
    ]
