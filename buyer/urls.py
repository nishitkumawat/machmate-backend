from django.urls import path
from . import views

urlpatterns = [
    path('projects/', views.get_projects, name='get_projects'),
    path('projects/create/', views.create_project, name='create_project'),
    path('projects/<int:project_id>/update/', views.update_project, name='update_project'),
    path('orders/completed/', views.get_completed_orders, name='get_completed_orders'),
    path('projects/<int:project_id>/quotations/', views.get_project_quotations, name='get_project_quotations'),
    path('quotations/<int:quotation_id>/accept/', views.accept_quotation, name='accept_quotation'),
    path('upload-pdf/', views.upload_pdf, name='upload_pdf'),
    path('projects/<int:project_id>/', views.delete_project, name='delete_project'),
]