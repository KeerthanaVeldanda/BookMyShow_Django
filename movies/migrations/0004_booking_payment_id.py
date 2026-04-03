from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("movies", "0003_alter_genre_options_alter_language_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="payment_id",
            field=models.CharField(db_index=True, default="TEMP_PAYMENT_ID", max_length=64),
            preserve_default=False,
        ),
    ]
