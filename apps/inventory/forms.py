from decimal import Decimal

from django import forms

from drugs.models import Batch, Category
from suppliers.models import Supplier
from purchases.models import PurchaseItem


class BulkPriceUpdateForm(forms.Form):
    """Increase or decrease the sale price (Batch.selling_price) of many
    products at once, scoped by a chosen audience."""

    DIRECTION_CHOICES = [
        ('increase', 'Increase'),
        ('decrease', 'Decrease'),
    ]
    SCOPE_CHOICES = [
        ('all', 'All products'),
        ('in_stock', 'In-stock products only (stock > 0)'),
        ('category', 'A specific category'),
        ('supplier', 'A specific supplier'),
    ]

    direction = forms.ChoiceField(choices=DIRECTION_CHOICES)
    percentage = forms.DecimalField(
        min_value=Decimal('0.01'),
        max_value=Decimal('1000'),
        max_digits=6,
        decimal_places=2,
        help_text='Percentage to apply, e.g. 10 for 10%.',
    )
    scope = forms.ChoiceField(choices=SCOPE_CHOICES)
    category = forms.ModelChoiceField(
        queryset=Category.objects.order_by('name'),
        required=False,
        empty_label='Select a category…',
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.order_by('name'),
        required=False,
        empty_label='Select a supplier…',
    )

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        direction = cleaned.get('direction')
        percentage = cleaned.get('percentage')

        if scope == 'category' and not cleaned.get('category'):
            self.add_error('category', 'Choose a category to update.')
        if scope == 'supplier' and not cleaned.get('supplier'):
            self.add_error('supplier', 'Choose a supplier to update.')

        # A decrease of 100% (or more) would wipe prices out entirely.
        if direction == 'decrease' and percentage is not None and percentage >= 100:
            self.add_error('percentage', 'A decrease must be less than 100%.')

        return cleaned

    @property
    def factor(self):
        """Multiplier applied to each price, e.g. 1.10 for +10%."""
        ratio = self.cleaned_data['percentage'] / Decimal('100')
        if self.cleaned_data['direction'] == 'decrease':
            return Decimal('1') - ratio
        return Decimal('1') + ratio

    def get_batches(self):
        """The Batch queryset whose selling_price will be updated."""
        scope = self.cleaned_data['scope']
        batches = Batch.objects.all()

        if scope == 'in_stock':
            batches = batches.filter(quantity__gt=0)
        elif scope == 'category':
            batches = batches.filter(drug__category=self.cleaned_data['category'])
        elif scope == 'supplier':
            # Batches have no direct supplier link; a product "comes from" a
            # supplier if it was ever purchased from them.
            drug_ids = (
                PurchaseItem.objects
                .filter(purchase__supplier=self.cleaned_data['supplier'])
                .values_list('drug_id', flat=True)
                .distinct()
            )
            batches = batches.filter(drug_id__in=drug_ids)

        return batches
