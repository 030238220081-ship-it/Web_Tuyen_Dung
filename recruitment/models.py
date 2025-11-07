from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
      ("recruiter", "Nhà tuyển dụng"),
      ("candidate", "Ứng viên"),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)

class JobPosting(models.Model):

    CATEGORY_CHOICES = (
        ('IT', 'Công nghệ thông tin'),
        ('BA', 'Business Analyst'),
        ('Tester', 'Kiểm thử phần mềm'),
        ('HR', 'Nhân sự'),
        ('Marketing', 'Marketing'),
        ('Sales', 'Kinh doanh'),
        ('Other', 'Khác'),
    )
    category = models.CharField(
        max_length=50, 
        choices=CATEGORY_CHOICES, 
        default='Other', 
        verbose_name="Ngành nghề"
    )
    
    recruiter = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=255, blank=True, null=True, verbose_name="Địa điểm")
    salary = models.CharField(max_length=255, blank=True, null=True, verbose_name="Mức lương")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Số lượng tuyển")
    benefits = models.TextField(blank=True, null=True, verbose_name="Phúc lợi")
    created_at = models.DateTimeField(auto_now_add=True)
    is_archived = models.BooleanField(default=False, verbose_name="Đã lưu trữ ")
    def __str__(self):
        return self.title

class Application(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Chờ xử lý'),
        ('invited', 'Đã mời phỏng vấn'),
        ('confirmed', 'Đã xác nhận phỏng vấn'),
        ('rejected', 'Đã từ chối'),
        ('passed', 'Đã trúng tuyển'), 
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name="Trạng thái")
    
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='application')
    candidate = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    cv = models.FileField(upload_to='cvs/')
    ai_score = models.FloatField(null=True, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_interview_questions = models.TextField(blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate.username} applied for {self.job.title}"
    
class Notification(models.Model):
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='notifications', verbose_name="Người nhận")
    message = models.TextField(verbose_name="Nội dung thông báo")
    action_url = models.CharField(max_length=255, blank=True, null=True, verbose_name="Link hành động")
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian tạo")

    def __str__(self):
        return f"Thông báo cho {self.recipient.username}: {self.message[:30]}"

    class Meta:
        ordering = ['-created_at']
    
class Profile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=255, blank=True)
    cv_file = models.FileField(upload_to='cvs/', blank=True, null=True)
    summary = models.TextField(default='', blank=True, verbose_name="Tóm tắt bản thân")
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True, verbose_name="Ảnh đại diện")
    
    def __str__(self):
        return self.user.username
    
class DirectMessage(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='messages', verbose_name="Hồ sơ")
    sender = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sent_messages', verbose_name="Người gửi")
    recipient = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='received_messages', verbose_name="Người nhận")
    content = models.TextField(verbose_name="Nội dung")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian")
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")

    def __str__(self):
        return f"Tin nhắn từ {self.sender.username} đến {self.recipient.username}"

    class Meta:
        ordering = ['timestamp']