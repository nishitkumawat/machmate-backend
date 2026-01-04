from django.contrib import admin
from .models import Users

@admin.register(Users)
class UsersAdmin(admin.ModelAdmin):
    list_display = (
        'user_id', 'name', 'email', 'phone', 'role',
        'plan', 'remaining_credits', 'created_at'
    )

    search_fields = ('name', 'email', 'phone')
    list_filter = ('role', 'plan')

    # Make it READ ONLY
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
