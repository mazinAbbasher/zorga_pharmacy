from django.shortcuts import render
from core.decorators import admin_only
from django.contrib.auth.decorators import login_required

@login_required
@admin_only
def index(request):
    return render(request, 'settings_app/index.html')
