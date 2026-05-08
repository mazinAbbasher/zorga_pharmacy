from django import forms
from .models import Customer, CustomerPayment

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone_number', 'address']
        # outstanding_balance removed to prevent manual edits

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'block w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-[1.25rem] text-sm font-medium focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all',
                'placeholder': self.fields[field].label
            })

class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ['amount', 'payment_mode', 'reference', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({
                'class': 'block w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-[1.25rem] text-sm font-medium focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all',
                'placeholder': self.fields[field].label
            })
