# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('company-details/', views.maker_company_details, name='maker_company_details'),
    path('projects/open/', views.maker_open_projects, name='maker_open_projects'),
    path('projects/<int:project_id>/quotation/', views.create_quotation, name='create_quotation'),
    path('quotations/', views.maker_quotations, name='maker_quotations'),
]