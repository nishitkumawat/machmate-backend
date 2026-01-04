from django.db import models

class Users(models.Model):
    user_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=50)
    created_at = models.DateTimeField()
    plan = models.CharField(max_length=50, null=True, blank=True)
    subscription_start_date = models.DateField(null=True, blank=True)
    subscription_end_date = models.DateField(null=True, blank=True)
    remaining_credits = models.IntegerField(null=True, blank=True)
    razorpay_subscription_id = models.CharField(max_length=255, null=True, blank=True)
    razorpay_customer_id = models.CharField(max_length=255, null=True, blank=True)
    referral_code = models.CharField(max_length=50, null=True, blank=True)
    referred_by = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        managed = False      # VERY IMPORTANT
        db_table = 'users'   # EXACT table name

    def __str__(self):
        return self.name
