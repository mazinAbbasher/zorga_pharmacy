from django.urls import path
from . import views

app_name = 'settings_app'

urlpatterns = [
    path('', views.index, name='index'),
    path('backup/download/', views.backup_download, name='backup_download'),
    path('backup/download/<str:name>/', views.backup_download_existing, name='backup_download_existing'),
    path('backup/delete/<str:name>/', views.backup_delete, name='backup_delete'),
    path('backup/restore/', views.restore, name='restore'),
]
