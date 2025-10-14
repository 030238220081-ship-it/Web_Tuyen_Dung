from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, JobPosting, Application, Profile, Question # Thêm các model khác nếu cần

class CustomUserAdmin(UserAdmin):
    model = CustomUser
    # Thêm 'user_type' vào danh sách hiển thị và form chỉnh sửa
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
admin.site.register(Question)