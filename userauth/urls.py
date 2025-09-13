from django.urls import path
from . import views

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("me/", views.me_view, name="me"),  # 👈
    
    path('profile/', views.get_user_profile, name='get_profile'),
    path('profile/update/', views.update_user_profile, name='update_profile'),
    path('profile/change-password/', views.change_password, name='change_password'),

]
