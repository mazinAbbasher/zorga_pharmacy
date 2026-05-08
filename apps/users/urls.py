from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('', views.list, name='list'),
    path('add/', views.create, name='create'),
    path('edit/<int:pk>/', views.edit, name='edit'),
    path('delete/<int:pk>/', views.delete, name='delete'),
]
