from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0002_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE FULLTEXT INDEX listing_search_ft "
                "ON listings_listing (title, description);",
            reverse_sql="DROP INDEX listing_search_ft ON listings_listing;",
        ),
    ]
