from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.index, name='index'),
    path('logs/', views.movement_logs, name='logs'),
    path('prices/bulk/', views.bulk_price_update, name='bulk_price'),
]
