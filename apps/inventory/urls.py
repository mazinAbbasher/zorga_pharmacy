from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.index, name='index'),
    path('logs/', views.movement_logs, name='logs'),
    path('prices/bulk/', views.bulk_price_update, name='bulk_price'),
    path('stock/<int:drug_pk>/adjust/', views.adjust_stock, name='adjust_stock'),
    path('stock/<int:drug_pk>/write-off/', views.write_off_expired, name='write_off_expired'),
]
