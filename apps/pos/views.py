import json

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from drugs.models import Drug
from .models import Sale, SaleItem
from django.contrib import messages
from decimal import Decimal
from django.db import transaction
from inventory.models import StockMovement
from django.template.defaultfilters import floatformat
from django.utils import timezone
from django.db.models import Q


def _cart_response(request, error=None, trigger=None):
    """Render the cart partial and attach an optional HX-Trigger event.

    The POS terminal listens for these events to give the cashier instant
    audio/visual feedback (scan accepted, not recognised, quantity capped).
    """
    context = _get_cart_context(request)
    if error:
        context['error'] = error
    response = render(request, 'pos/partials/cart.html', context)
    if trigger:
        response['HX-Trigger'] = json.dumps(trigger)
    return response

@login_required
def index(request):
    """Main POS Terminal View"""
    if 'cart' not in request.session:
        request.session['cart'] = {}
    
    context = _get_cart_context(request)
    from customers.models import Customer
    context['customers'] = Customer.objects.all()
    context['all_drugs'] = Drug.objects.all().order_by('trade_name')
    
    # Define payment options for the premium UI
    context['payment_options'] = [
        ('CASH', 'banknote', 'Cash'),
        ('CARD', 'credit-card', 'Card'),
        ('BANK_TRANSFER', 'smartphone-nfc', 'Transfer'),
        ('CREDIT', 'user-plus', 'Credit'),
    ]

    return render(request, 'pos/index.html', context)

@login_required
def search_drugs(request):
    """HTMX: Search for drugs in real-time"""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return render(request, 'pos/partials/search_results.html', {'drugs': []})

    drugs = Drug.objects.filter(
        Q(trade_name__icontains=query) |
        Q(scientific_name__icontains=query) |
        Q(barcode__iexact=query)
    ).distinct()[:10]
    
    return render(request, 'pos/partials/search_results.html', {'drugs': drugs})

@login_required
def add_to_cart(request):
    """HTMX: Add a drug to the session cart"""
    barcode = (request.POST.get('barcode') or '').strip()
    drug_id = request.POST.get('drug_id')

    drug = None
    if barcode:
        drug = Drug.objects.filter(barcode__iexact=barcode).first()
        if not drug:
            # Fallback to exact trade name match if they typed it manually
            drug = Drug.objects.filter(trade_name__iexact=barcode).first()
    elif drug_id:
        drug = Drug.objects.filter(id=drug_id).first()
        
    if not drug:
        label = barcode or 'item'
        return _cart_response(request, error=f'Not recognised: {label}',
                              trigger={'scanError': {'message': f'Not recognised: {label}'}})

    if drug.total_quantity <= 0:
        return _cart_response(request, error=f'Out of stock: {drug.trade_name}',
                              trigger={'scanError': {'message': f'Out of stock: {drug.trade_name}'}})

    cart = request.session.get('cart', {})
    str_id = str(drug.id)

    current_qty = cart.get(str_id, {}).get('quantity', 0)
    if current_qty + 1 > drug.total_quantity:
        msg = f'Only {drug.total_quantity} of {drug.trade_name} in stock'
        return _cart_response(request, error=msg, trigger={'scanError': {'message': msg}})

    if str_id in cart:
        cart[str_id]['quantity'] += 1
    else:
        # Store current price and name to decouple from future drug field changes during the session
        cart[str_id] = {
            'price': str(drug.current_price),
            'quantity': 1,
            'name': drug.trade_name
        }

    request.session['cart'] = cart
    request.session.modified = True

    return _cart_response(request, trigger={'scanSuccess': {'name': drug.trade_name}})

@login_required
def update_cart(request, drug_id):
    """HTMX: Update quantity in the session cart"""
    try:
        quantity = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        quantity = 1
        
    cart = request.session.get('cart', {})
    str_id = str(drug_id)
    trigger = None

    if str_id in cart:
        if quantity > 0:
            drug = get_object_or_404(Drug, id=drug_id)
            if quantity > drug.total_quantity:
                msg = f"Only {drug.total_quantity} of {drug.trade_name} in stock"
                trigger = {'posToast': {'message': msg, 'level': 'warning'}}
                quantity = drug.total_quantity
            cart[str_id]['quantity'] = quantity
        else:
            del cart[str_id]

    request.session['cart'] = cart
    request.session.modified = True

    return _cart_response(request, trigger=trigger)

@login_required
def remove_from_cart(request, drug_id):
    """HTMX: Remove item from cart"""
    cart = request.session.get('cart', {})
    str_id = str(drug_id)
    if str_id in cart:
        del cart[str_id]
    request.session['cart'] = cart
    request.session.modified = True
    return _cart_response(request)

@login_required
def clear_cart(request):
    """HTMX: Empty the whole cart in one action."""
    request.session['cart'] = {}
    request.session.modified = True
    return _cart_response(request)

@login_required
@transaction.atomic
def checkout(request):
    """Finalize Sale: Dedact stock (FIFO) and create Sale records"""
    cart = request.session.get('cart', {})
    if not cart:
        messages.error(request, "Cart is empty.")
        return redirect('pos:index')
    
    payment_method = request.POST.get('payment_method', 'CASH')
    try:
        discount = Decimal(request.POST.get('discount', '0.00'))
        if discount < 0:
            discount = Decimal('0.00')
    except (ValueError, TypeError):
        discount = Decimal('0.00')
        
    customer_id = request.POST.get('customer_id')
    
    customer = None
    if customer_id:
        from customers.models import Customer
        customer = Customer.objects.filter(id=customer_id).first()
    
    if payment_method == 'CREDIT' and not customer:
        messages.error(request, "A customer must be selected for credit payments.")
        return redirect('pos:index')
    
    # 1. First Pass: Validate and Prep (Calculate Total based on Session Prices)
    total_amount = Decimal('0.00')
    for drug_id, item in cart.items():
        total_amount += Decimal(item['price']) * item['quantity']
        
    if total_amount < discount:
        messages.error(request, "Discount cannot exceed total amount.")
        return redirect('pos:index')

    # 2. Create Sale Record
    sale = Sale.objects.create(
        cashier=request.user,
        customer=customer,
        total_amount=total_amount,
        discount=discount,
        payment_method=payment_method
    )
    
    # 3. Deduct Stock and Create SaleItems (FIFO)
    today = timezone.now().date()
    for drug_id, item in cart.items():
        drug = Drug.objects.get(id=drug_id)
        qty_to_deduct = item['quantity']
        
        # FIFO: oldest batch first, excluding expired
        batches = drug.batches.filter(quantity__gt=0, expiry_date__gte=today).order_by('created_at')
        
        for batch in batches:
            if qty_to_deduct <= 0: break
                
            deduct = min(batch.quantity, qty_to_deduct)
            
            # Create SaleItem with precise cost mapping
            SaleItem.objects.create(
                sale=sale,
                drug=drug,
                quantity=deduct,
                unit_price=Decimal(item['price']),
                unit_cost=batch.purchase_price,
                total_price=Decimal(item['price']) * deduct,
                total_cost=batch.purchase_price * deduct
            )
            
            # Update batch stock
            batch.quantity -= deduct
            batch.save()
            
            # Audit Trail: Log the explicit movement for this specific batch
            StockMovement.objects.create(
                drug=drug,
                movement_type='OUT',
                quantity=deduct,
                reference_id=f"SALE-{sale.id}",
                user=request.user,
                notes=f"Sold from Batch {batch.batch_number} (Expiry: {batch.expiry_date})"
            )
            
            
            qty_to_deduct -= deduct
            
        if qty_to_deduct > 0:
            transaction.set_rollback(True)
            messages.error(request, f"Insufficient unexpired stock for {drug.trade_name} during checkout.")
            return redirect('pos:index')

    # 4. Success and Cleanup
    request.session['cart'] = {}
    request.session.modified = True
    
    messages.success(request, f"Sale #{sale.id} completed. Total: SDG {floatformat(total_amount - discount, 0)}")
    return redirect('pos:index')

@login_required
def print_invoice(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)
    return render(request, 'pos/invoice_print.html', {'sale': sale})

@login_required
@transaction.atomic
def refund_invoice(request, sale_id):
    """Refund a sale and restore stock to the latest batch"""
    sale = get_object_or_404(Sale, pk=sale_id)
    if sale.is_refunded:
        messages.warning(request, "This sale has already been refunded.")
        return redirect('dashboard:index')
        
    if request.method == 'POST':
        for item in sale.items.all():
            drug = item.drug
            # Restore to the latest batch (even if expired, to prevent stock loss)
            latest_batch = drug.batches.all().order_by('-created_at').first()
            if latest_batch:
                latest_batch.quantity += item.quantity
                latest_batch.save()
            
            StockMovement.objects.create(
                drug=drug,
                movement_type='RETURN',
                quantity=item.quantity,
                reference_id=f"REF-{sale.id}",
                user=request.user,
                notes=f"Refunded Sale #{sale.id}"
            )
        
        sale.is_refunded = True
        sale.refund_timestamp = timezone.now()
        sale.save()
            
        messages.success(request, f"Sale #{sale_id} refunded and stock restored.")
        return redirect('dashboard:index')
    
    return render(request, 'pos/confirm_refund.html', {'sale': sale})

def _get_cart_context(request):
    """Simple cart context based on session data"""
    cart = request.session.get('cart', {})
    cart_items = []
    subtotal = Decimal('0.00')
    
    for drug_id, item in cart.items():
        try:
            drug = Drug.objects.get(id=drug_id)
        except Drug.DoesNotExist:
            continue
            
        qty = item['quantity']
        price = Decimal(item['price'])
        total = price * qty
        
        cart_items.append({
            'drug': drug,
            'quantity': qty,
            'price': price,
            'total': total
        })
        subtotal += total
        
    return {
        'cart_items': cart_items,
        'subtotal': subtotal
    }
