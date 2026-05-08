from django.urls import path
from . import views

app_name = 'drugs'

urlpatterns = [
    path('', views.list, name='list'),
    path('insights/<int:pk>/', views.stock_insights, name='stock_insights'),
    path('add/', views.create, name='create'),
    path('edit/<int:pk>/', views.update, name='update'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    
    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_create, name='category_create'),
    path('categories/edit/<int:pk>/', views.category_update, name='category_update'),
    path('categories/delete/<int:pk>/', views.category_delete, name='category_delete'),
]
