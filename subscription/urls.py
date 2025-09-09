from django.urls import path
from . import views

urlpatterns = [
    path('user-subscription/', views.user_subscription, name='user_subscription'),
    path('create-payment/', views.create_payment, name='create_payment'),
    path('verify-payment/', views.verify_payment, name='verify_payment'),
    path('cancel-subscription/', views.cancel_subscription, name='cancel_subscription'),
    path('check-credits/', views.check_credits, name='check_credits'),
    path('use-credit/', views.use_credit, name='use_credit'),
]