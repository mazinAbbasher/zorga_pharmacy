from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import User
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib import messages

from core.decorators import admin_only
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'role', 'phone_number')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].widget.attrs.update({'class': 'w-full px-4 py-2 rounded-xl border border-slate-200 focus:ring-2 focus:ring-accent-500 focus:border-transparent transition-all outline-none'})

class CustomUserChangeForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'role', 'phone_number', 'is_active')
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            if field != 'is_active':
                self.fields[field].widget.attrs.update({'class': 'w-full px-4 py-2 rounded-xl border border-slate-200 focus:ring-2 focus:ring-accent-500 focus:border-transparent transition-all outline-none'})

@login_required
@admin_only
def list(request):
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'users/list.html', {'users': users})

@login_required
@admin_only
def create(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "User created successfully.")
            return redirect('users:list')
    else:
        form = CustomUserCreationForm()
    return render(request, 'users/form.html', {'form': form, 'title': 'Create New User'})

@login_required
@admin_only
def edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = CustomUserChangeForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "User updated successfully.")
            return redirect('users:list')
    else:
        form = CustomUserChangeForm(instance=user)
    return render(request, 'users/form.html', {'form': form, 'title': f'Edit User: {user.username}', 'is_edit': True})

@login_required
@admin_only
def delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('users:list')
    
    if request.method == 'POST':
        user.delete()
        messages.success(request, "User deleted successfully.")
        return redirect('users:list')
    return render(request, 'users/confirm_delete.html', {'user_obj': user})
