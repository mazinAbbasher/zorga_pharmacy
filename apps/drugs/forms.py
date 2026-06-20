from decimal import Decimal

from django import forms
from .models import Drug, Category

class DrugForm(forms.ModelForm):
    sale_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False, label="Current Sale Price (SDG)", help_text="Updates the price for all active stock.")
    # Current buy/replacement cost. Editing this revalues on-hand stock so the
    # inventory value tracks the live market — without touching past purchase
    # invoices (PurchaseItem) or already-recorded sale costs (SaleItem.unit_cost).
    buy_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal('0'), label="Current Buy Price (SDG)", help_text="Revalues active stock; past purchase invoices are unaffected.")

    class Meta:
        model = Drug
        fields = [
            'trade_name', 'scientific_name', 'manufacturer', 'category',
            'barcode', 'dispensing_strategy', 'minimum_stock_alert'
        ]

    def clean_barcode(self):
        # Normalise to a trimmed value, and store an empty barcode as NULL so
        # that multiple products without a barcode don't collide on the unique
        # constraint (empty strings would).
        barcode = (self.cleaned_data.get('barcode') or '').strip()
        return barcode or None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['sale_price'].initial = self.instance.current_price
            self.fields['buy_price'].initial = self.instance.current_buy_price

        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'block w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-[1.25rem] text-sm font-medium focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all',
                'placeholder': field.label
            })
            
    def save(self, commit=True):
        drug = super().save(commit=commit)
        if commit and drug.pk:
            from django.utils import timezone
            today = timezone.now().date()
            # Cascade only to active (non-expired) batches, including FIFO
            # products that carry no expiry date. Historical records live in
            # separate tables and are never touched here.
            active = drug.batches.filter(Drug._not_expired(today))
            new_sale = self.cleaned_data.get('sale_price')
            if new_sale is not None:
                active.update(selling_price=new_sale)
            new_buy = self.cleaned_data.get('buy_price')
            if new_buy is not None:
                active.update(purchase_price=new_buy)
        return drug

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'block w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-[1.25rem] text-sm font-medium focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all',
                'placeholder': field.label
            })
