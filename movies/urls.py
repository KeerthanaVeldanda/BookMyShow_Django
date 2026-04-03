from django.urls import path
from . import views
urlpatterns=[
    path('',views.movie_list,name='movie_list'),
    path('admin/dashboard/', views.admin_analytics_dashboard, name='admin_analytics_dashboard'),
    path('<int:movie_id>/theaters',views.theater_list,name='theater_list'),
    path('theater/<int:theater_id>/seats/book/',views.book_seats,name='book_seats'),
    path('theater/<int:theater_id>/payments/order/', views.create_payment_order, name='create_payment_order'),
    path('payments/verify/', views.verify_payment, name='verify_payment'),
    path('payments/failure/', views.payment_failure, name='payment_failure'),
    path('payments/webhook/razorpay/', views.razorpay_webhook, name='razorpay_webhook'),
]