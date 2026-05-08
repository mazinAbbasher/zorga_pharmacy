from django.urls import path
from . import views

app_name = 'transactions'

urlpatterns = [
    path('', views.list, name='list'),
    path('sale/<int:pk>/', views.sale_detail, name='sale_detail'),
    path('purchase/<int:pk>/', views.purchase_detail, name='purchase_detail'),
]
