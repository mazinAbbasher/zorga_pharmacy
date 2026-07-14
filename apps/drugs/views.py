from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, F, Sum, Value, Exists, OuterRef, DecimalField
from django.db.models.functions import Coalesce
from .models import Drug, Category, Manufacturer, Batch
from .selectors import restock_needed_drugs, expiring_soon_count, EXPIRING_SOON_DAYS
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
    query = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '')
    stock_status = request.GET.get('status', '')
    expiry_status = request.GET.get('expiry', '')

    today = timezone.now().date()
    not_expired = Q(batches__expiry_date__gte=today) | Q(batches__expiry_date__isnull=True)

    # Base list query. select_related + prefetch_related means the per-row
    # template properties (stock_status, current_price, nearest_expiry_date, …)
    # read from cache instead of firing a query each — this is what removed the
    # multi-second load. ``sellable_qty`` / ``expired_qty`` are annotated so the
    # stock/expiry filters run in the database rather than in Python.
    drugs = (
        Drug.objects
        .select_related('category', 'manufacturer')
        .prefetch_related('batches')
        .annotate(
            sellable_qty=Coalesce(Sum('batches__quantity', filter=not_expired), Value(0)),
            expired_qty=Coalesce(
                Sum('batches__quantity', filter=Q(batches__expiry_date__lt=today)), Value(0)
            ),
        )
        .order_by('trade_name')
    )

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

    # Stock Status Filter (mirrors Drug.stock_status: OUT = 0 sellable,
    # LOW = 0 < sellable <= threshold, RESTOCK = either of those).
    if stock_status == 'low':
        drugs = drugs.filter(sellable_qty__gt=0, sellable_qty__lte=F('minimum_stock_alert'))
    elif stock_status == 'out':
        drugs = drugs.filter(sellable_qty__lte=0)
    elif stock_status == 'restock':
        drugs = drugs.filter(sellable_qty__lte=F('minimum_stock_alert'))

    # Expiry Filter
    if expiry_status == 'expired':
        drugs = drugs.filter(expired_qty__gt=0)
    elif expiry_status == 'soon':
        soon_window = Batch.objects.filter(
            drug=OuterRef('pk'),
            quantity__gt=0,
            expiry_date__gte=today,
            expiry_date__lte=today + timedelta(days=EXPIRING_SOON_DAYS),
        )
        drugs = drugs.filter(Exists(soon_window))

    # HTMX filter/search requests only swap the table body, so skip the headline
    # stats and filter-dropdown data — just return the rows.
    if request.headers.get('HX-Request') and request.headers.get('HX-Target') != 'modal-content':
        return render(request, 'drugs/partials/drug_list_rows.html', {'drugs': drugs})

    # Full-page render: headline stats via dedicated aggregate queries (not by
    # walking every drug in Python).
    restock_total = restock_needed_drugs(today).count()
    out_of_stock_count = (
        Drug.objects
        .annotate(sellable_qty=Coalesce(Sum('batches__quantity', filter=not_expired), Value(0)))
        .filter(sellable_qty__lte=0)
        .count()
    )
    stats = {
        'total_products': Drug.objects.count(),
        'out_of_stock_count': out_of_stock_count,
        'low_stock_count': restock_total - out_of_stock_count,
        'expiring_soon_count': expiring_soon_count(today=today),
    }
    # Cost/retail valuation is admin-only (hidden from pharmacists) and is the
    # one genuinely expensive figure, so only compute it when it will be shown.
    if request.user.is_admin():
        money = DecimalField(max_digits=16, decimal_places=2)
        valuation = (
            Batch.objects.filter(Drug._not_expired(today), quantity__gt=0)
            .aggregate(
                cost=Sum(F('quantity') * F('purchase_price'), output_field=money),
                retail=Sum(F('quantity') * F('selling_price'), output_field=money),
            )
        )
        stats['total_valuation'] = valuation['cost'] or Decimal('0.00')
        stats['total_retail_valuation'] = valuation['retail'] or Decimal('0.00')

    context = {
        'drugs': drugs,
        'query': query,
        'categories': Category.objects.all().order_by('name'),
        'selected_category': category_id,
        'selected_status': stock_status,
        'selected_expiry': expiry_status,
        'stats': stats,
    }
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


# Manufacturer Views
def _render_manufacturer_list_response(request, success_msg=None):
    if success_msg:
        messages.success(request, success_msg)
    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
@pharmacist_or_admin
def manufacturer_list(request):
    manufacturers = Manufacturer.objects.all().order_by('name')
    if request.headers.get('HX-Request') and not request.headers.get('HX-Target') == 'modal-content':
        return render(request, 'drugs/partials/manufacturer_list_rows.html', {'manufacturers': manufacturers})
    return render(request, 'drugs/manufacturer_list.html', {'manufacturers': manufacturers})

@login_required
@pharmacist_or_admin
def manufacturer_create(request):
    from .forms import ManufacturerForm
    if request.method == 'POST':
        form = ManufacturerForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_manufacturer_list_response(request, "Manufacturer created successfully.")
            return redirect('drugs:manufacturer_list')
    else:
        form = ManufacturerForm()

    template = 'drugs/partials/manufacturer_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Create New Manufacturer'})

@login_required
@pharmacist_or_admin
def manufacturer_update(request, pk):
    from .forms import ManufacturerForm
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        form = ManufacturerForm(request.POST, instance=manufacturer)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_manufacturer_list_response(request, "Manufacturer updated successfully.")
            return redirect('drugs:manufacturer_list')
    else:
        form = ManufacturerForm(instance=manufacturer)

    template = 'drugs/partials/manufacturer_form_modal.html' if request.headers.get('HX-Request') else 'drugs/form.html'
    return render(request, template, {'form': form, 'title': 'Edit Manufacturer', 'manufacturer': manufacturer})

@login_required
@pharmacist_or_admin
def manufacturer_delete(request, pk):
    manufacturer = get_object_or_404(Manufacturer, pk=pk)
    if request.method == 'POST':
        manufacturer.delete()
        if request.headers.get('HX-Request'):
            return _render_manufacturer_list_response(request, "Manufacturer deleted successfully.")
        return redirect('drugs:manufacturer_list')

    template = 'drugs/partials/confirm_manufacturer_delete_modal.html' if request.headers.get('HX-Request') else 'drugs/confirm_delete.html'
    return render(request, template, {'manufacturer': manufacturer})
