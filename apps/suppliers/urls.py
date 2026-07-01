from django.urls import path
from . import views

app_name = 'suppliers'

urlpatterns = [
    path('', views.list, name='list'),
    path('add/', views.create, name='create'),
    path('edit/<int:pk>/', views.update, name='update'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('pay/<int:pk>/', views.record_payment, name='record_payment'),
    path('payments/edit/<int:pk>/', views.update_payment, name='update_payment'),
    path('payments/delete/<int:pk>/', views.delete_payment, name='delete_payment'),
    path('statement/<int:pk>/', views.statement, name='statement'),
]
