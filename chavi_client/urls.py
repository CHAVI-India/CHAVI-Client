"""
URL configuration for chavi_client project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.shortcuts import redirect
from client_app.views import documentation_view, HomePageView
from client_app.admin import get_custom_admin_urls
from django.conf import settings

# Add custom admin URLs to the admin site
admin.site.get_urls = lambda: get_custom_admin_urls() + admin.site.__class__.get_urls(admin.site)

urlpatterns = [
    # path('admin/doc/', include('django.contrib.admindocs.urls')), 
    # path('grappelli/', include('grappelli.urls')), # grappelli URLS    
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    # API endpoints
    path('api/lookup/', include('lookup.urls')),
    # Select2 URLs for autocomplete
    path('select2/', include('django_select2.urls')),
    # Data import workflow
    path('import/', include('data_import.urls')),
    # Include client_app URLs with namespace
    path('', include('client_app.urls')),
    # Home URL now points to the homepage view instead of redirecting
    path('home/', HomePageView.as_view(), name='home'),
    # Documentation URLs
    re_path(r'^docs/(?P<path>.*)$', documentation_view, name='documentation'),
    path('docs/', documentation_view, name='documentation-index'),
]

# Configure custom error handlers
if settings.DEBUG:
    # In DEBUG mode, we need to explicitly set the handler
    from client_app.views import custom_403_view
    handler403 = custom_403_view
