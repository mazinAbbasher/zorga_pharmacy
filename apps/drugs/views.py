from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from .models import Drug, Category
from .forms import DrugForm
from django.contrib import messages
from core.decorators import pharmacist_or_admin
from django.http import HttpResponse

from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

def _render_drug_list_response(request, success_msg=None):
    if success_msg:
        messages.success(request, success_msg)
    from django.http import HttpResponse
    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
def list(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')
    stock_status = request.GET.get('status', '')
    expiry_status = request.GET.get('expiry', '')
    
    drugs = Drug.objects.all().order_by('trade_name')
    today = timezone.now().date()
    
    # Category Filter
    if category_id:
        try:
            category_id = int(category_id)
            drugs = drugs.filter(category_id=category_id)
        except (ValueError, TypeError):
            category_id = ''
    
    # Text Search
    if query:
        drugs = drugs.filter(
            Q(trade_name__icontains=query) | 
            Q(scientific_name__icontains=query) |
            Q(barcode__icontains=query)
        )
        
    # Stock Status Filter
    if stock_status == 'low':
        drugs = [d for d in drugs if d.stock_status == 'LOW_STOCK']
    elif stock_status == 'out':
        drugs = [d for d in drugs if d.stock_status == 'OUT_OF_STOCK']
        
    # Expiry Filter
    if expiry_status == 'expired':
        drugs = [d for d in drugs if d.nearest_expiry_date and d.nearest_expiry_date < today]
    elif expiry_status == 'soon':
        ninety_days_away = today + timedelta(days=90)
        drugs = [d for d in drugs if d.nearest_expiry_date and today <= d.nearest_expiry_date <= ninety_days_away]

    # Dashboard Stats
    all_drugs = Drug.objects.all()
    stats = {
        'total_products': all_drugs.count(),
        'low_stock_count': len([d for d in all_drugs if d.stock_status == 'LOW_STOCK']),
        'out_of_stock_count': len([d for d in all_drugs if d.stock_status == 'OUT_OF_STOCK']),
        'expiring_soon_count': len([d for d in all_drugs if d.nearest_expiry_date and today <= d.nearest_expiry_date <= today + timedelta(days=90)]),
        'total_valuation': sum(d.total_inventory_value for d in all_drugs),
    }
    
    categories = Category.objects.all().order_by('name')
    
    context = {
        'drugs': drugs,
        'query': query,
        'categories': categories,
        'selected_category': category_id,
        'selected_status': stock_status,
        'selected_expiry': expiry_status,
        'stats': stats,
    }

    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'modal-content':
        return render(request, 'drugs/partials/drug_list_rows.html', context)
    
    return render(request, 'drugs/index.html', context)

@login_required
def stock_insights(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    batches = drug.batches.all().order_by('expiry_date')
    today = timezone.now().date()
    soon = today + timedelta(days=90)
    
    from inventory.models import StockMovement
    movements = StockMovement.objects.filter(drug=drug).order_by('-timestamp')[:5]
    
    return render(request, 'drugs/partials/drug_insights.html', {
        'drug': drug,
        'batches': batches,
        'movements': movements,
        'today': today,
        'soon': soon
    })

@login_required
@pharmacist_or_admin
def create(request):
    if request.method == 'POST':
        form = DrugForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_drug_list_response(request, "Drug added successfully.")
            messages.success(request, "Drug added successfully.")
            return redirect('drugs:list')
    else:
        form = DrugForm()
    
    template = 'drugs/partials/drug_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Register New Drug'})

@login_required
@pharmacist_or_admin
def update(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    if request.method == 'POST':
        form = DrugForm(request.POST, instance=drug)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_drug_list_response(request, "Drug updated successfully.")
            messages.success(request, "Drug updated successfully.")
            return redirect('drugs:list')
    else:
        form = DrugForm(instance=drug)
    
    template = 'drugs/partials/drug_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Edit Drug', 'drug': drug})

@login_required
@pharmacist_or_admin
def delete(request, pk):
    drug = get_object_or_404(Drug, pk=pk)
    if request.method == 'POST':
        from django.db.models import ProtectedError
        try:
            drug.delete()
            if request.headers.get('HX-Request'):
                return _render_drug_list_response(request, "Drug deleted successfully.")
            messages.success(request, "Drug deleted successfully.")
            return redirect('drugs:list')
        except ProtectedError:
            messages.error(request, "Cannot delete drug: It has associated purchase or sales records.")
            if request.headers.get('HX-Request'):
                return _render_drug_list_response(request)
            return redirect('drugs:list')
    
    template = 'drugs/partials/confirm_delete_modal.html' if request.headers.get('HX-Request') else 'drugs/confirm_delete.html'
    return render(request, template, {'drug': drug})


# Category Views
def _render_category_list_response(request, success_msg=None):
    if success_msg:
        messages.success(request, success_msg)
    from django.http import HttpResponse
    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
@pharmacist_or_admin
def category_list(request):
    categories = Category.objects.all().order_by('name')
    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'modal-content':
        return render(request, 'drugs/partials/category_list_rows.html', {'categories': categories})
    return render(request, 'drugs/category_list.html', {'categories': categories})

@login_required
@pharmacist_or_admin
def category_create(request):
    from .forms import CategoryForm
    if request.method == 'POST':
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_category_list_response(request, "Category created successfully.")
            return redirect('drugs:category_list')
    else:
        form = CategoryForm()
    
    template = 'drugs/partials/category_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Create New Category'})

@login_required
@pharmacist_or_admin
def category_update(request, pk):
    from .forms import CategoryForm
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_category_list_response(request, "Category updated successfully.")
            return redirect('drugs:category_list')
    else:
        form = CategoryForm(instance=category)
    
    template = 'drugs/partials/category_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Edit Category', 'category': category})

@login_required
@pharmacist_or_admin
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        category.delete()
        if request.headers.get('HX-Request'):
            return _render_category_list_response(request, "Category deleted successfully.")
        return redirect('drugs:category_list')
    
    template = 'drugs/partials/confirm_category_delete_modal.html' if request.headers.get('HX-Request') else 'drugs/confirm_delete.html'
    return render(request, template, {'category': category})
