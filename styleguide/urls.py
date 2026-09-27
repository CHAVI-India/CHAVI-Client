from django.urls import path

from . import views

app_name = 'styleguide'

urlpatterns = [
    path('', views.styleguide_view, name='index'),
]
