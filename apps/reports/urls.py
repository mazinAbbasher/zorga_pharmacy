from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.index, name='index'),
    path('dead-stock/', views.dead_stock, name='dead_stock'),
    path('loss-report/', views.loss_report, name='loss_report'),
    path('stock-valuation/', views.stock_valuation, name='stock_valuation'),
]
