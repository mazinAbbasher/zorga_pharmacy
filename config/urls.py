from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.templatetags.static import static as static_url
from django.views.generic.base import RedirectView


def home(request):
    """Send each user to their landing page: admins to the dashboard, everyone
    else (pharmacists) to the POS terminal. Keeps the revenue/profit dashboard
    out of a pharmacist's path entirely."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_admin():
        return redirect('dashboard:index')
    return redirect('pos:index')


urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static_url('logo.png'), permanent=True)),

    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    path('', home, name='home'),

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
