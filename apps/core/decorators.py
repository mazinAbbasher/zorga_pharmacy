from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from functools import wraps

def role_required(allowed_roles):
    """
    Decorator for views that checks if the user has one of the allowed roles.
    allowed_roles: list of strings (e.g., ['ADMIN', 'PHARMACIST'])
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if request.user.is_superuser or request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)
            raise PermissionDenied
        return _wrapped_view
    return decorator

def admin_only(view_func):
    return role_required(['ADMIN'])(view_func)

def pharmacist_or_admin(view_func):
    return role_required(['ADMIN', 'PHARMACIST'])(view_func)
