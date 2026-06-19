from django import forms
from django.forms import inlineformset_factory

from .models import Purchase, PurchaseItem


_HEADER_INPUT = (
    'w-full bg-slate-50 border border-slate-200 rounded-2xl px-5 py-4 text-slate-900 '
    'placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-accent-500/10 '
    'focus:border-accent-500 transition-all font-medium'
)

# Compact controls used inside the multi-line product table.
_CELL_INPUT = (
    'w-full bg-white border border-slate-200 rounded-lg px-3 py-2 text-sm text-slate-900 '
    'placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-accent-500/20 '
    'focus:border-accent-500 transition-all'
)


class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ['supplier', 'invoice_number', 'purchase_date']
        widgets = {
            'purchase_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': _HEADER_INPUT})


class PurchaseItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ['drug', 'batch_number', 'quantity', 'purchase_price', 'selling_price', 'expiry_date']
        widgets = {
            'expiry_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Whether batch number / expiry are required depends on the selected
        # drug's strategy (FEFO requires both; FIFO takes neither), so make them
        # optional at field level and enforce the rule in clean().
        self.fields['batch_number'].required = False
        self.fields['expiry_date'].required = False

        placeholders = {
            'batch_number': 'Batch #',
            'quantity': 'Qty',
            'purchase_price': 'Buy',
            'selling_price': 'Sell',
        }
        for name, field in self.fields.items():
            field.widget.attrs['class'] = _CELL_INPUT
            if name in placeholders:
                field.widget.attrs['placeholder'] = placeholders[name]

    def clean(self):
        cleaned = super().clean()
        drug = cleaned.get('drug')
        batch = (cleaned.get('batch_number') or '').strip()
        expiry = cleaned.get('expiry_date')
        if not drug:
            return cleaned

        if drug.dispensing_strategy == 'FEFO':
            # FEFO products are batch- and expiry-tracked.
            if not batch:
                self.add_error('batch_number', 'Batch number is required for FEFO products.')
            if not expiry:
                self.add_error('expiry_date', 'Expiry date is required for FEFO products.')
            cleaned['batch_number'] = batch
        else:
            # FIFO products are not batch-tracked; ignore any batch number.
            cleaned['batch_number'] = ''
        return cleaned


# Multiple product lines per purchase. extra=1 shows one blank row; the template
# clones the empty form to add more, and can_delete lets rows be removed.
PurchaseItemFormSet = inlineformset_factory(
    Purchase,
    PurchaseItem,
    form=PurchaseItemForm,
    extra=1,
    can_delete=True,
)
