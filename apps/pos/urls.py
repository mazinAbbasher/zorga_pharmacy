from django.urls import path
from . import views

app_name = 'pos'

urlpatterns = [
    path('', views.index, name='index'),
    path('search-drugs/', views.search_drugs, name='search_drugs'),
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('update-cart/<int:drug_id>/', views.update_cart, name='update_cart'),
    path('remove-from-cart/<int:drug_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('clear-cart/', views.clear_cart, name='clear_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('invoice/<int:sale_id>/', views.print_invoice, name='print_invoice'),
    path('refund/<int:sale_id>/', views.refund_invoice, name='refund_invoice'),
]
