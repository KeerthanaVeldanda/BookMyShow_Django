from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0004_booking_payment_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='movie',
            name='trailer_url',
            field=models.URLField(blank=True, null=True),
        ),
    ]
