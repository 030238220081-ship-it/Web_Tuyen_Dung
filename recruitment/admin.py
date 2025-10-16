from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, JobPosting, Application, Profile

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'user_type', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('user_type',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (None, {'fields': ('user_type',)}),
    )

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(JobPosting)
admin.site.register(Application)
admin.site.register(Profile)