import django.db.models.deletion
from django.db import migrations, models


def create_manufacturers_from_text(apps, schema_editor):
    """Turn each distinct non-empty free-text manufacturer into a Manufacturer
    row and point the drug at it, so no existing data is lost."""
    Drug = apps.get_model('drugs', 'Drug')
    Manufacturer = apps.get_model('drugs', 'Manufacturer')

    cache = {}
    for drug in Drug.objects.exclude(manufacturer_legacy='').exclude(manufacturer_legacy__isnull=True):
        name = drug.manufacturer_legacy.strip()
        if not name:
            continue
        key = name.lower()
        maker = cache.get(key)
        if maker is None:
            maker, _ = Manufacturer.objects.get_or_create(name=name)
            cache[key] = maker
        drug.manufacturer = maker
        drug.save(update_fields=['manufacturer'])


def restore_text_from_manufacturers(apps, schema_editor):
    """Reverse: copy the manufacturer name back into the legacy text field."""
    Drug = apps.get_model('drugs', 'Drug')
    for drug in Drug.objects.filter(manufacturer__isnull=False):
        drug.manufacturer_legacy = drug.manufacturer.name
        drug.save(update_fields=['manufacturer_legacy'])


class Migration(migrations.Migration):

    dependencies = [
        ('drugs', '0004_alter_batch_expiry_date'),
    ]

    operations = [
        migrations.CreateModel(
            name='Manufacturer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('description', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        # Preserve the current free-text values while we swap the field type.
        migrations.RenameField(
            model_name='drug',
            old_name='manufacturer',
            new_name='manufacturer_legacy',
        ),
        migrations.AddField(
            model_name='drug',
            name='manufacturer',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='drugs', to='drugs.manufacturer'),
        ),
        migrations.RunPython(create_manufacturers_from_text, restore_text_from_manufacturers),
        migrations.RemoveField(
            model_name='drug',
            name='manufacturer_legacy',
        ),
    ]
