from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = (
      ("recruiter", "Nhà tuyển dụng"),
      ("candidate", "Ứng viên"),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)

class JobPosting(models.Model):
    recruiter = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=255, blank=True, null=True, verbose_name="Địa điểm")
    salary = models.CharField(max_length=255, blank=True, null=True, verbose_name="Mức lương")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Số lượng tuyển")
    benefits = models.TextField(blank=True, null=True, verbose_name="Phúc lợi")
    created_at = models.DateTimeField(auto_now_add=True)
    time_limit = models.PositiveIntegerField(default=15, verbose_name="Thời gian làm bài (phút)")

    def __str__(self):
        return self.title

class Application(models.Model):
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
    is_read = models.BooleanField(default=False, verbose_name="Đã đọc")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Thời gian tạo")

    def __str__(self):
        return f"Thông báo cho {self.recipient.username}: {self.message[:30]}"

    class Meta:
        ordering = ['-created_at']

class Interview(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE, verbose_name="Hồ sơ ứng tuyển")
    hr_notes = models.TextField(verbose_name="Ghi chú của HR (Câu trả lời của UV)")
    ai_analysis = models.JSONField(null=True, blank=True, verbose_name="Phân tích chi tiết từ AI")
    ai_score = models.IntegerField(default=0, verbose_name="Điểm phỏng vấn từ AI")
    interview_date = models.DateTimeField(auto_now_add=True, verbose_name="Ngày phỏng vấn")

    def __str__(self):
        return f"Phỏng vấn cho {self.application.candidate.username} vị trí {self.application.job.title}"
    
class Question(models.Model):
    QUESTION_TYPES = [('MC', 'Trắc nghiệm'), ('ESSAY', 'Tự luận')]
    job_posting = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='questions')
    text = models.CharField(max_length=500)
    question_type = models.CharField(max_length=5, choices=QUESTION_TYPES, default='MC')

    def __str__(self):
        return self.text

class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.question.text[:30]}... -> {self.text}"

class QuizResult(models.Model):
    application = models.OneToOneField(Application, on_delete=models.CASCADE)
    score = models.FloatField()
    correct_answers = models.PositiveIntegerField()
    total_questions = models.PositiveIntegerField()
    completed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Kết quả của {self.application.candidate.username} cho vị trí {self.application.job.title}"
    
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

class EssayAnswer(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    answer_text = models.TextField()

    def __str__(self):
        return f"Câu trả lời của {self.application.candidate.username} cho câu hỏi '{self.question.text[:30]}...'"

class Profile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=255, blank=True)
    cv_file = models.FileField(upload_to='cvs/', null=True, blank=True)

    summary = models.TextField(blank=True)

    def __str__(self):
        return self.user.username