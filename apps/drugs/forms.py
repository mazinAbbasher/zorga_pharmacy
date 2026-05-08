from django import forms
from .models import Drug, Category

class DrugForm(forms.ModelForm):
    sale_price = forms.DecimalField(max_digits=12, decimal_places=2, required=False, label="Current Sale Price (SDG)", help_text="Updates the price for all active stock.")

    class Meta:
        model = Drug
        fields = [
            'trade_name', 'scientific_name', 'manufacturer', 'category',
            'barcode', 'minimum_stock_alert'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['sale_price'].initial = self.instance.current_price
            
        for field_name, field in self.fields.items():
            field.widget.attrs.update({
                'class': 'block w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-[1.25rem] text-sm font-medium focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all',
                'placeholder': field.label
            })
            
    def save(self, commit=True):
        drug = super().save(commit=commit)
        new_price = self.cleaned_data.get('sale_price')
        if new_price is not None and commit and drug.pk:
            from django.utils import timezone
            today = timezone.now().date()
            drug.batches.filter(expiry_date__gte=today).update(selling_price=new_price)
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
