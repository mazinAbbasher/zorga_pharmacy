from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from core.decorators import admin_only, pharmacist_or_admin
from pos.models import Sale
from purchases.models import Purchase
from django.db.models import Q

@login_required
@pharmacist_or_admin
def list(request):
    query = request.GET.get('q', '')
    transaction_type = request.GET.get('type', 'sales') # default to sales
    
    # Only admins may view purchases; everyone else (and the default) sees sales.
    if transaction_type == 'purchases' and request.user.is_admin():
        transactions = Purchase.objects.all().order_by('-created_at')
        if query:
            transactions = transactions.filter(
                Q(invoice_number__icontains=query) |
                Q(supplier__name__icontains=query)
            )
        template = 'transactions/purchase_list.html'
    else:
        transaction_type = 'sales'
        transactions = Sale.objects.all().order_by('-timestamp')
        if query:
            transactions = transactions.filter(
                Q(id__icontains=query) |
                Q(customer__name__icontains=query)
            )
        template = 'transactions/sale_list.html'

    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'modal-content':
        partial_template = 'transactions/partials/purchase_rows.html' if transaction_type == 'purchases' else 'transactions/partials/sale_rows.html'
        return render(request, partial_template, {'transactions': transactions})

    return render(request, template, {
        'transactions': transactions,
        'query': query,
        'type': transaction_type
    })

@login_required
@pharmacist_or_admin
def sale_detail(request, pk):
    sale = get_object_or_404(Sale, pk=pk)
    return render(request, 'transactions/partials/sale_detail_modal.html', {'sale': sale})

@login_required
@admin_only
def purchase_detail(request, pk):
    purchase = get_object_or_404(Purchase, pk=pk)
    return render(request, 'transactions/partials/purchase_detail_modal.html', {'purchase': purchase})
