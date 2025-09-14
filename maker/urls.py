# urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('company-details/', views.maker_company_details, name='maker_company_details'),
    path('projects/open/', views.maker_open_projects, name='maker_open_projects'),
    path('projects/<int:project_id>/quotation/', views.create_quotation, name='create_quotation'),
    path('quotations/', views.maker_quotations, name='maker_quotations'),
    
    
    # path('company-details/', views.get_company_profile, name='get-company-details'),
    path('company-details/create/', views.manage_company_profile, name='create-company-details'),
    path('company-details/update/', views.manage_company_profile, name='update-company-details'),
    path('profiles/', views.get_all_maker_profiles, name='get-all-maker-profiles'),
    path('profiles/<int:maker_id>/', views.get_maker_profile_by_id, name='get-maker-profile-by-id'),
]