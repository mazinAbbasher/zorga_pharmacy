from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    
    path('', lambda r: redirect('dashboard:index')),
    
    path('dashboard/', include('dashboard.urls')),
    path('drugs/', include('drugs.urls')),
    path('pos/', include('pos.urls')),
    path('purchases/', include('purchases.urls')),
    path('inventory/', include('inventory.urls')),
    path('suppliers/', include('suppliers.urls')),
    path('customers/', include('customers.urls')),
    path('reports/', include('reports.urls')),
    path('transactions/', include('transactions.urls')),
    path('settings/', include('settings_app.urls')),
    path('users/', include('users.urls')),
]
