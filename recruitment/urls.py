from django.urls import path
from . import views

urlpatterns = [
    # --- URL Chính & Xác thực ---
    path('', views.job_list_view, name='job_list'),
    path('login/', views.login_view, name='login'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('logout/', views.logout_view, name='logout'), # Thêm URL đăng xuất nếu bạn chưa có

    # --- URL cho Ứng viên (Candidate) ---
    path('jobs/', views.job_board_view, name='job_board'),
    path('profile/', views.profile_view, name='profile'),
    path('job-matches/', views.job_match_view, name='job_matches'),
    path('cv-review/', views.cv_review_view, name='cv_review'),
    path('notifications/', views.notification_list_view, name='notifications'),
    path('chatbot/', views.chatbot_view, name='chatbot'),
    path('api/chat/', views.chat_api_view, name='chat_api'),

    # --- URL cho Nhà tuyển dụng (Recruiter) ---
    path('dashboard/', views.recruiter_dashboard, name='recruiter_dashboard'),
    path('create-job/', views.create_job, name='create_job'),
    path('create-job/review/', views.create_job_review, name='create_job_review'),
    path('search-candidates/', views.search_candidates_view, name='search_candidates'),
    path('candidate/<int:user_id>/', views.view_candidate_profile, name='view_candidate_profile'),
    path('analytics/', views.recruitment_analytics_view, name='recruitment_analytics'),

    # --- URL liên quan đến một Vị trí tuyển dụng cụ thể (Job Posting) ---
    path('job/<int:job_id>/', views.job_detail, name='job_detail'),
    path('job/<int:job_id>/edit/', views.edit_job_view, name='edit_job'),
    path('job/<int:job_id>/delete/', views.delete_job_view, name='delete_job'),
    path('job/<int:job_id>/applicants/', views.applicant_list_view, name='applicant_list'),
    path('job/<int:job_id>/generate-quiz/', views.generate_quiz_view, name='generate_quiz'),

    # --- URL liên quan đến một Hồ sơ ứng tuyển cụ thể (Application) ---
    path('application/<int:application_id>/re-analyze/', views.re_analyze_application_view, name='re_analyze_application'),
    path('application/<int:application_id>/invite/', views.send_interview_invitation_view, name='send_invitation'),
    path('application/<int:application_id>/interview-questions/', views.generate_interview_questions, name='interview_questions'),
    path('application/<int:application_id>/conduct-interview/', views.conduct_interview_view, name='conduct_interview'),
    path('application/<int:application_id>/take-quiz/', views.take_quiz_view, name='take_quiz'),
    path('application/<int:job_id>/apply-with-profile/', views.apply_with_profile_view, name='apply_with_profile'),
]