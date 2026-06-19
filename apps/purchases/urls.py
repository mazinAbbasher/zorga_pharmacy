from django.urls import path
from . import views

app_name = 'purchases'

urlpatterns = [
    path('', views.list, name='list'),
    path('add/', views.create, name='create'),
    path('return/<int:pk>/', views.return_purchase, name='return_purchase'),
]
