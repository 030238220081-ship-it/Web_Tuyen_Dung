import json, fitz, docx, groq, random, re, traceback, datetime
from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, login, logout
from .forms import CustomUserCreationForm, ProfileForm, RecruiterProfileForm
from django.urls import reverse_lazy
from django.views import generic
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Max, OuterRef, Exists, Avg, Sum
from django.urls import reverse
from django.http import JsonResponse
from .utils import extract_text_from_cv
from django.contrib.auth.forms import AuthenticationForm
from django.db.models.functions import TruncDate
from .models import JobPosting, Application, Profile, Notification, DirectMessage, EmailTemplate, Interview
from django.template import Context, Template

CustomUser = get_user_model()

DEFAULT_TEMPLATES = {
    'invite': """Chào bạn {{candidate_name}},

Cảm ơn bạn đã ứng tuyển vào vị trí {{job_title}} tại công ty chúng tôi.

Chúng tôi rất ấn tượng với hồ sơ của bạn và trân trọng mời bạn tham gia một buổi phỏng vấn:
- Thời gian: {{interview_time}}
- Địa điểm: {{interview_location}}

Ghi chú thêm: {{custom_message}}

Vui lòng xác nhận lại lịch hẹn này.

Trân trọng,
{{recruiter_name}}""",
    
    'reject_cv': """Chào bạn {{candidate_name}},

Cảm ơn bạn đã quan tâm và ứng tuyển vào vị trí {{job_title}}.

Sau khi xem xét cẩn thận, chúng tôi nhận thấy hồ sơ của bạn chưa hoàn toàn phù hợp với các yêu cầu của vị trí này ở thời điểm hiện tại.
{{custom_message}}

Chúng tôi sẽ lưu lại hồ sơ của bạn và liên hệ khi có cơ hội khác phù hợp hơn.
Chúc bạn may mắn.

Trân trọng,
{{recruiter_name}}""",
    
    'pass': """Chào bạn {{candidate_name}},

Chúc mừng! Chúng tôi rất vui mừng thông báo bạn đã CHÍNH THỨC trúng tuyển vị trí {{job_title}} tại công ty chúng tôi.

Chúng tôi tin rằng kỹ năng và kinh nghiệm của bạn sẽ là một sự bổ sung tuyệt vời cho đội ngũ.
Ghi chú thêm: {{custom_message}}

Chúng tôi sẽ sớm liên hệ với bạn để thảo luận về các bước tiếp theo.

Trân trọng,
{{recruiter_name}}""",
    
    'reject_interview': """Chào bạn {{candidate_name}},

Cảm ơn bạn đã dành thời gian tham gia phỏng vấn cho vị trí {{job_title}}.
Chúng tôi đánh giá cao nỗ lực của bạn.

Tuy nhiên, sau khi cân nhắc kỹ lưỡng, chúng tôi rất tiếc phải thông báo rằng chúng tôi sẽ tiếp tục với các ứng viên khác phù hợp hơn.
{{custom_message}}

Chúc bạn mọi điều tốt đẹp và may mắn trong hành trình tìm kiếm công việc.

Trân trọng,
{{recruiter_name}}"""
}

VIETNAM_PROVINCES = [
    "Hà Nội",
    "Hồ Chí Minh",
    "Đà Nẵng",
    "Hải Phòng",
    "Cần Thơ",
    "Bắc Ninh",
    "Bình Dương",
    "Đồng Nai",
    "Khánh Hòa",
    "Quảng Ninh",
]

def extract_text_from_cv(cv_file):
    text = ""
    try:
        cv_file.seek(0)
        if cv_file.name.lower().endswith('.pdf'):
            with fitz.open(stream=cv_file.read(), filetype="pdf") as doc:
                for page in doc:
                    text += page.get_text()
        elif cv_file.name.lower().endswith('.docx'):
            doc = docx.Document(cv_file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        else:
            text = "Định dạng file không được hỗ trợ (chỉ hỗ trợ PDF và DOCX)."
    except Exception as e:
        print(f"Lỗi khi đọc file CV: {e}")
    return text

@login_required
def create_job(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list')
        
    if request.method == 'POST':
        title = request.POST.get('title')
        keywords = request.POST.get('keywords')
        years_experience = request.POST.get('experience')
        prompt = f"Viết một JD cho vị trí '{title}', yêu cầu kinh nghiệm {years_experience} năm và kỹ năng: {keywords}. JD gồm 3 phần: Mô tả công việc, Yêu cầu, và Quyền lợi."

        generated_jd = "Không thể tạo JD."
        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant",
            )
            generated_jd = chat_completion.choices[0].message.content
        except Exception as e:
            print(f"Lỗi Groq API khi tạo JD: {e}")
            messages.error(request, 'AI đang gặp sự cố, vui lòng thử lại.')
            return redirect('create_job')

        request.session['jd_title'] = title
        request.session['generated_jd'] = generated_jd.strip()

        return redirect('create_job_review')

    archived_jobs = JobPosting.objects.filter(
        recruiter=request.user, 
        is_archived=True
    ).order_by('-created_at')
    
    context = {
        'archived_jobs': archived_jobs
    }
    return render(request, 'recruitment/create_job.html', context)

@login_required
def job_detail(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id)
    my_application = None 
    
    if request.user.is_authenticated and request.user.user_type == 'candidate':
        try:
            my_application = Application.objects.get(job=job, candidate=request.user)
        except Application.DoesNotExist:
            my_application = None

    if request.method == 'POST' and request.user.user_type == 'candidate':
        cv_file = request.FILES.get('cv')
        if not cv_file:
            messages.error(request, 'Vui lòng chọn một file CV để nộp.')
            return redirect('job_detail', job_id=job_id)
        
        cv_text = extract_text_from_cv(cv_file)
        if not cv_text:
            messages.error(request, 'Không thể đọc được file CV. Chỉ hỗ trợ PDF và DOCX.')
            return redirect('job_detail', job_id=job_id)

        prompt = f"""Phân tích JD và CV dưới đây.
        JD: {job.description}
        CV: {cv_text}
        Hãy trả về kết quả là một chuỗi json và không có bất kỳ văn bản nào khác. Json object phải có 2 key: "score" (với thang điểm từ 0-100) và "summary" """
        
        ai_score, ai_summary = 0, "Không thể phân tích."
        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Bạn là một AI chuyên sàng lọc CV, chỉ trả về kết quả dưới dạng JSON."},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.1-8b-instant" 
            )
            response_text = chat_completion.choices[0].message.content
            ai_result = json.loads(response_text)
            ai_score = ai_result.get('score', 0)
            ai_summary = ai_result.get('summary', 'Lỗi tóm tắt.')
        except Exception as e:
            print(f"Lỗi Groq API khi sàng lọc CV (job_detail POST): {e}")

        new_application = Application.objects.create(
            job=job, 
            candidate=request.user, 
            cv=cv_file, 
            ai_score=ai_score, 
            ai_summary=ai_summary
        )
        
        set_as_default = request.POST.get('set_as_default')
        if set_as_default:
            try:
                profile = request.user.profile
                profile.cv_file = new_application.cv 
                profile.save()
            except Profile.DoesNotExist:
                Profile.objects.create(user=request.user, cv_file=new_application.cv)
        
        messages.success(request, 'Bạn đã nộp hồ sơ thành công!')
        return redirect('job_detail', job_id=job_id)
        
    return render(request, 'recruitment/job_detail.html', {'job': job, 'my_application': my_application})

@login_required
def chat_api_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_message = data.get('message')
        prompt = f"""Bạn là một trợ lý tuyển dụng AI thân thiện. Hãy trả lời câu hỏi của ứng viên một cách ngắn gọn, hữu ích. Câu hỏi: "{user_message}" """
        
        bot_response = "Lỗi kết nối đến AI."
        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant"
            )
            bot_response = chat_completion.choices[0].message.content
        except Exception as e:
            print(f"Lỗi Groq API (Chatbot): {e}")

        return JsonResponse({'response': bot_response.strip()})
    return JsonResponse({'error': 'Invalid request method'}, status=405)
class RegisterView(generic.CreateView):
    form_class = CustomUserCreationForm
    template_name = 'registration/register.html'
    
    def get_success_url(self):
        return reverse_lazy('login')

    def form_valid(self, form):
        user_type = self.request.POST.get('user_type')
        if not user_type:
            form.add_error(None, 'Vui lòng chọn loại tài khoản (Ứng viên hoặc Nhà tuyển dụng).')
            return self.form_invalid(form)
        user = form.save(commit=False)
        user.user_type = user_type
        user.set_password(form.cleaned_data["password"]) 
        user.save()
        
        Profile.objects.create(user=user)
        
        messages.success(self.request, 'Tài khoản đã được tạo thành công! Vui lòng đăng nhập.')
        return redirect(self.get_success_url())
    
@login_required
def profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)

    if request.user.user_type == 'candidate':
        FormClass = ProfileForm 
    else:
        FormClass = RecruiterProfileForm 

    if request.method == 'POST':
        form = FormClass(request.POST, request.FILES, instance=profile)
        
        if form.is_valid():
            form.save()
            messages.success(request, 'Hồ sơ của bạn đã được cập nhật thành công!')
            return redirect('profile') 
        else:
            messages.error(request, 'Vui lòng kiểm tra lại các thông tin đã nhập.')
    else:
        form = FormClass(instance=profile)

    context = {
        'form': form,
        'profile': profile
    }
    return render(request, 'recruitment/profile.html', context)

@login_required
def recruiter_dashboard(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list')
        
    jobs = JobPosting.objects.filter(
        recruiter=request.user, 
        is_archived=False
    ).annotate(
        application_count=Count('application')
    ).order_by('-created_at')
    
    total_jobs_posted = jobs.count()
    total_applications_received = sum(job.application_count for job in jobs)
    
    upcoming_interviews = Interview.objects.filter(
        application__job__recruiter=request.user,
        application__status='confirmed', 
        interview_date__gte=timezone.now() 
    ).select_related(
        'application__candidate', 'application__job'
    ).order_by('interview_date')[:5] 

    context = {
        'jobs': jobs, 
        'total_jobs_posted': total_jobs_posted,
        'total_applications_received': total_applications_received,
        'upcoming_interviews': upcoming_interviews, 
    }
    return render(request, 'recruitment/recruiter_dashboard.html', context)

@login_required
def applicant_list_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    applications = Application.objects.filter(job=job).select_related('candidate__profile')

    context = {
        'job': job,
        'applications': applications
    }
    return render(request, 'recruitment/applicant_list.html', context)

@login_required
def chatbot_view(request):
    return render(request, 'recruitment/chatbot.html')

@login_required
def job_match_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    if not profile.cv_file:
        context = {'has_cv': False}
        return render(request, 'recruitment/job_matches.html', context)

    try:
        cv_text = extract_text_from_cv(profile.cv_file)
        if not cv_text:
            context = {'error_message': 'Không thể đọc được nội dung từ file CV của bạn.'}
            return render(request, 'recruitment/job_matches.html', context)

        print("\n--- BẮT ĐẦU PHÂN TÍCH TÌM VIỆC ---")
        print(f"NỘI DUNG CV ĐÃ ĐỌC (150 ký tự đầu): {cv_text[:150]}...")
        print("------------------------------------")

        all_jobs = JobPosting.objects.all()
        matched_jobs_with_scores = []

        for job in all_jobs:
            print(f"Đang phân tích Job: '{job.title}'")
            score = get_ai_match_score(cv_text, job.description)
            print(f"-> Điểm AI trả về: {score}") 
            
            if score > 20:
                job.match_score = score
                matched_jobs_with_scores.append(job)
                print("-> KẾT QUẢ: Job được thêm vào danh sách.")
            else:
                print("-> KẾT QUẢ: Job bị loại do điểm thấp.")
            print("---") 

        matched_jobs_with_scores.sort(key=lambda x: x.match_score, reverse=True)
                
        context = {
            'has_cv': True,
            'matched_jobs': matched_jobs_with_scores
        }
        return render(request, 'recruitment/job_matches.html', context)
        
    except Exception as e:
        print(f"Lỗi nghiêm trọng trong job_match_view: {e}")
        context = {'error_message': 'Đã có lỗi nghiêm trọng xảy ra trong quá trình tìm kiếm.'}
        return render(request, 'recruitment/job_matches.html', context)

@login_required
def apply_with_profile_view(request, job_id):
    if request.user.user_type != 'candidate':
        messages.error(request, 'Chỉ có ứng viên mới có thể ứng tuyển.')
        return redirect('job_list')

    job = get_object_or_404(JobPosting, pk=job_id)
    profile = get_object_or_404(Profile, user=request.user)

    if Application.objects.filter(job=job, candidate=request.user).exists():
        messages.warning(request, f'Bạn đã ứng tuyển vào vị trí "{job.title}" trước đó rồi.')
        return redirect('job_detail', job_id=job_id) 

    if not profile.cv_file:
        messages.error(request, 'Bạn chưa có CV trong hồ sơ để ứng tuyển.')
        return redirect('profile')

    Application.objects.create(
        job=job, 
        candidate=request.user, 
        cv=profile.cv_file, 
        ai_score=0, 
        ai_summary="Ứng tuyển bằng hồ sơ có sẵn. (Chưa chạy phân tích)" 
    )

    messages.success(request, f'Bạn đã ứng tuyển thành công vào vị trí "{job.title}"!')
    
    return redirect('job_detail', job_id=job_id)

@login_required
def analyze_cv_for_job_api(request):
    if request.method != 'POST' or request.user.user_type != 'candidate':
        return JsonResponse({'success': False, 'error': 'Yêu cầu không hợp lệ'}, status=400)

    try:
        job_id = request.POST.get('job_id')
        cv_file = request.FILES.get('cv_file') 
        use_profile_cv = request.POST.get('use_profile_cv') 
        
        job = get_object_or_404(JobPosting, pk=job_id)
        profile, _ = Profile.objects.get_or_create(user=request.user)
        
        cv_text = ""
        if cv_file:
            cv_text = extract_text_from_cv(cv_file)
        elif use_profile_cv == 'true':
            if not profile.cv_file:
                return JsonResponse({'success': False, 'error': 'Bạn chưa tải CV lên hồ sơ.'})
            cv_text = extract_text_from_cv(profile.cv_file)
        else:
            return JsonResponse({'success': False, 'error': 'Không tìm thấy CV để phân tích.'})

        if not cv_text:
            return JsonResponse({'success': False, 'error': 'Không thể đọc được file CV.'})

        ai_score = get_ai_match_score(cv_text, job.description)
        
        analysis_prompt = f"""
        Một ứng viên có CV đạt {ai_score} điểm. Dựa trên CV và JD dưới đây, hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác.
        JSON object chỉ cần có 2 key:
        1. "strengths": (list) 2-3 điểm mạnh cụ thể.
        2. "suggestions": (list) 2-3 gợi ý cải thiện.
        
        --- CV ---
        {cv_text}
        --- JD ---
        {job.description}
        """
        
        ai_strengths = []
        ai_suggestions = []

        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": analysis_prompt}],
            model="llama-3.1-8b-instant"
        )
        response_text = chat_completion.choices[0].message.content
        
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        json_str = json_match.group(1) if json_match else response_text
            
        analysis_data = json.loads(json_str)
        ai_strengths = analysis_data.get("strengths", ["AI không tìm thấy điểm mạnh."])
        ai_suggestions = analysis_data.get("suggestions", ["AI không có gợi ý cải thiện."])
        
        return JsonResponse({'success': True, 'data': {
            'score': ai_score,
            'strengths': ai_strengths,
            'suggestions': ai_suggestions
        }})

    except Exception as e:
        print(f"Lỗi API (analyze_cv_for_job_api): {e}")
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': 'Lỗi máy chủ khi đang phân tích AI.'}, status=500)
    
@login_required
def create_job_review(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        location = request.POST.get('location')
        salary = request.POST.get('salary')
        quantity = request.POST.get('quantity')
        benefits = request.POST.get('benefits')
        if title and description:
            JobPosting.objects.create(
                recruiter=request.user, 
                title=title, 
                description=description,
                location=location,
                salary=salary,
                quantity=quantity,
                benefits=benefits
            )
            messages.success(request, 'Bạn đã đăng tin tuyển dụng thành công!')
            return redirect('recruiter_dashboard')

    title = request.session.get('jd_title', '')
    generated_jd = request.session.get('generated_jd', '')
    context = {
        'title': title,
        'generated_jd': generated_jd,
        'categories': JobPosting.CATEGORY_CHOICES
    }
    return render(request, 'recruitment/create_job_review.html', context)

@login_required
def delete_job_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    
    if request.method == 'POST':
        job.is_archived = True
        job.save()
        messages.success(request, f'Đã chuyển tin tuyển dụng "{job.title}" vào kho lưu trữ.')
        return redirect('recruiter_dashboard')
    
    return render(request, 'recruitment/delete_job_confirm.html', {'job': job})

@login_required
def edit_job_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)

    if request.method == 'POST':
        job.title = request.POST.get('title', job.title)
        job.location = request.POST.get('location', job.location)
        job.salary = request.POST.get('salary', job.salary)
        job.quantity = request.POST.get('quantity', job.quantity)
        job.benefits = request.POST.get('benefits', job.benefits)
        job.description = request.POST.get('description', job.description)
        job.category = request.POST.get('category', job.category) 
        job.save()
        messages.success(request, f'Đã cập nhật thành công tin tuyển dụng "{job.title}".')
        return redirect('recruiter_dashboard')

    context = {'job': job,
               'categories': JobPosting.CATEGORY_CHOICES
    }
    
    return render(request, 'recruitment/edit_job.html', context)


@login_required
def re_analyze_application_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, job__recruiter=request.user)
    
    cv_text = extract_text_from_cv(application.cv)
    if not cv_text:
        messages.error(request, 'Không thể đọc được file CV của ứng viên này.')
        return redirect('applicant_list', job_id=application.job.id)

    prompt = f"""Phân tích JD và CV dưới đây.
    JD: {application.job.description}
    CV: {cv_text}
    Hãy trả về kết quả là MỘT CHUỖI JSON HỢP LỆ và KHÔNG có bất kỳ văn bản nào khác. JSON object phải có 2 key: "score" (số nguyên từ 0-100) và "summary" (tóm tắt 3 điểm mạnh nhất)."""
    
    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Bạn là một AI chuyên sàng lọc CV, chỉ trả về kết quả dưới dạng JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant"
        )
        response_text = chat_completion.choices[0].message.content
        ai_result = json.loads(response_text)
        
        application.ai_score = ai_result.get('score', 0)
        application.ai_summary = ai_result.get('summary', 'Lỗi tóm tắt.')
        application.save()
        
        messages.success(request, f'Đã phân tích thành công hồ sơ của {application.candidate.username}.')

    except Exception as e:
        print(f"Lỗi Groq API khi phân tích lại CV: {e}")
        messages.error(request, 'AI đang gặp sự cố, không thể phân tích hồ sơ này.')

    return redirect('applicant_list', job_id=application.job.id)

@login_required
def confirm_interview_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, candidate=request.user)

    if application.status == 'confirmed':
        messages.warning(request, 'Bạn đã xác nhận phỏng vấn cho vị trí này trước đó.')
        return redirect('notifications')
        
    if request.method == 'POST':
        application.status = 'confirmed'
        application.save()
        
        message_content = f"Ứng viên '{request.user.username}' đã XÁC NHẬN phỏng vấn cho vị trí '{application.job.title}'."
        
        applicant_list_url = request.build_absolute_uri(
            reverse('applicant_list', kwargs={'job_id': application.job.id})
        )
        
        Notification.objects.create(
            recipient=application.job.recruiter,
            message=message_content,
            action_url=applicant_list_url
        )
        
        messages.success(request, 'Bạn đã xác nhận lời mời. Nhà tuyển dụng sẽ sớm liên hệ với bạn.')
        return redirect('notifications')

    context = {'application': application}
    return render(request, 'recruitment/confirm_interview.html', context)

@login_required
def notification_list_view(request):
    notifications = Notification.objects.filter(recipient=request.user)
    context = {'notifications': notifications}
    
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    
    return render(request, 'recruitment/notifications.html', context)


@login_required
def cv_review_view(request):
    if request.method == 'POST':
        response_text = ""
        try:
            profile = request.user.profile
            if not profile.cv_file:
                return JsonResponse({'success': False, 'error': 'Bạn chưa tải lên CV.'})
            
            cv_text = extract_text_from_cv(profile.cv_file)
            if not cv_text:
                return JsonResponse({'success': False, 'error': 'Không thể đọc nội dung file CV.'})

            data = json.loads(request.body)
            job_id = data.get('job_id')
            if not job_id:
                return JsonResponse({'success': False, 'error': 'Vui lòng chọn một vị trí công việc.'})

            job = get_object_or_404(JobPosting, pk=job_id)
            jd_text = job.description
            score = get_ai_match_score(cv_text, jd_text) 
            analysis_prompt = f"""
            Một ứng viên có CV đạt {score} điểm (trên thang 100) khi so sánh với một Mô tả công việc.
            Dựa trên CV và JD dưới đây, hãy đóng vai một chuyên gia tư vấn sự nghiệp và đưa ra phân tích.
            
            --- CV ---
            {cv_text}
            --- JD ---
            {jd_text}

            Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác, bọc trong cặp dấu ```json ... ```.
            JSON object chỉ cần có 2 key:
            1. "strengths": (list) 2-3 điểm mạnh cụ thể của CV so với JD.
            2. "suggestions": (list) 2-3 gợi ý cải thiện mang tính hành động cao.
            """
            
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": analysis_prompt}],
                model="llama-3.1-8b-instant" 
            )
            response_text = chat_completion.choices[0].message.content
            
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text
            analysis_data = json.loads(json_str)
            final_response_data = {
                "score": score,
                "strengths": analysis_data.get("strengths", []), 
                "suggestions": analysis_data.get("suggestions", [])
            }
            
            return JsonResponse({'success': True, 'data': final_response_data})

        except Exception as e:
            print("--- LỖI NGHIÊM TRỌNG KHI PHÂN TÍCH CV ---")
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': 'Đã có lỗi nghiêm trọng xảy ra phía máy chủ.'})
    
    else:
        all_jobs = JobPosting.objects.all()
        context = {'jobs': all_jobs}
        return render(request, 'recruitment/cv_review.html', context)
    
@login_required
def recruitment_analytics_view(request):
    selected_month = request.GET.get('month', '')
    selected_job_title = request.GET.get('job_title', '')
    recruiter = request.user    
    recruiter_jobs_query = JobPosting.objects.filter(
        recruiter=recruiter, 
        is_archived=False
    )
    
    if selected_month:
        recruiter_jobs_query = recruiter_jobs_query.filter(created_at__month=selected_month)
    if selected_job_title:
        recruiter_jobs_query = recruiter_jobs_query.filter(title=selected_job_title)

    jobs_grouped_stats = recruiter_jobs_query.values('title').annotate(
        total_planned=Sum('quantity'),
        
        total_actual=Count('application', filter=Q(application__status='passed'))
        
    ).order_by('title')

    job_titles_comparison = [job['title'] for job in jobs_grouped_stats]
    planned_quantity = [job['total_planned'] for job in jobs_grouped_stats]
    actual_applications = [job['total_actual'] for job in jobs_grouped_stats]

    kpi_percentages = [
        round((actual / planned) * 100, 1) if planned > 0 else 0
        for actual, planned in zip(actual_applications, planned_quantity)
    ]
    
    dynamic_label = "Thực hiện (Trúng tuyển)" 
    label_parts = []
    if selected_month:
        label_parts.append(f"Tháng {selected_month}")
    if selected_job_title:
        label_parts.append(selected_job_title)
    if label_parts:
        dynamic_label += f" ({' & '.join(label_parts)})"
    
    all_applications_query = Application.objects.filter(
        job__recruiter=recruiter, 
        job__is_archived=False
    )
    
    if selected_month:
        all_applications_query = all_applications_query.filter(applied_at__month=selected_month)
    if selected_job_title:
        all_applications_query = all_applications_query.filter(job__title=selected_job_title)

    total_applications = all_applications_query.count()
    processed_applications = all_applications_query.exclude(status='pending').count()
    response_rate = round((processed_applications / total_applications) * 100, 1) if total_applications > 0 else 0
    invited_count = all_applications_query.filter(status__in=['invited', 'confirmed']).count()
    avg_ai_score_data = all_applications_query.filter(ai_score__gt=0).aggregate(avg_score=Avg('ai_score'))
    avg_ai_score = round(avg_ai_score_data['avg_score'], 1) if avg_ai_score_data['avg_score'] else 0

    status_map = dict(Application.STATUS_CHOICES)
    status_distribution = all_applications_query.values('status').annotate(count=Count('status')).order_by('status')
    
    funnel_labels = [status_map.get(s['status'], s['status']) for s in status_distribution]
    funnel_data = [s['count'] for s in status_distribution]

    trend_data = all_applications_query.annotate(
        date=TruncDate('applied_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('date')
    
    trend_labels = [d['date'].strftime('%d/%m') for d in trend_data]
    trend_counts = [d['count'] for d in trend_data]

    chart_colors = [
        f'rgba({random.randint(0, 255)}, {random.randint(0, 255)}, {random.randint(0, 255)}, 0.7)'
        for _ in range(len(job_titles_comparison))
    ]
    
    all_job_titles_for_filter = JobPosting.objects.filter(
        recruiter=recruiter,
        is_archived=False
    ).order_by('title').values_list('title', flat=True).distinct()

    context = {
        'total_applications': total_applications,
        'response_rate': response_rate,
        'invited_count': invited_count,
        'avg_ai_score': avg_ai_score,
        
        'funnel_labels_json': json.dumps(funnel_labels),
        'funnel_data_json': json.dumps(funnel_data),
        
        'trend_labels_json': json.dumps(trend_labels),
        'trend_counts_json': json.dumps(trend_counts),
        
        'job_titles_comparison_json': json.dumps(job_titles_comparison),
        'actual_applications_json': json.dumps(actual_applications),
        'planned_quantity_json': json.dumps(planned_quantity),
        'kpi_percentages_json': json.dumps(kpi_percentages),
        'chart_colors_json': json.dumps(chart_colors),
        'dynamic_label': dynamic_label,
        
        'all_job_titles_for_filter': all_job_titles_for_filter,
        'months': range(1, 13), 
        'selected_month': int(selected_month) if selected_month else None,
        'selected_job_title': selected_job_title,
    }
    return render(request, 'recruitment/recruitment_analytics.html', context)

@login_required
def analytics_summary_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            kpi_data = data.get('kpi_data', {})
            funnel_data = data.get('funnel_data', {})

            funnel_str = "\n".join([f"- {label}: {count}" for label, count in funnel_data.items()])

            prompt = f"""
            Bạn là một chuyên gia phân tích dữ liệu tuyển dụng
            Dưới đây là các số liệu từ dashboard tuyển dụng của tôi
            
            Số liệu tổng quan:
            - Tổng hồ sơ nhận được: {kpi_data.get('total_applications')}
            - Tỷ lệ tôi đã phản hồi (mời/từ chối): {kpi_data.get('response_rate')}%
            - Số hồ sơ tôi đã mời phỏng vấn: {kpi_data.get('invited_count')}
            - Điểm AI trung bình của hồ sơ: {kpi_data.get('avg_ai_score')} / 100

            Phân bổ trạng thái hồ sơ:
            {funnel_str}

            Dựa trên các số liệu này, hãy đưa ra 3 NHẬN XÉT ngắn gọn và 1 GỢI Ý HÀNH ĐỘNG để cải thiện quy trình.
            Sử dụng giọng văn chuyên nghiệp, đi thẳng vào vấn đề.
            """

            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant", 
            )
            ai_analysis = chat_completion.choices[0].message.content

            return JsonResponse({'success': True, 'analysis': ai_analysis})

        except Exception as e:
            print(f"Lỗi AI Analytics: {e}")
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)

def get_ai_match_score(cv_text, jd_text):
    response_content = "" 
    try:
        prompt = f"""
        Bạn là một chuyên gia tuyển dụng, hãy tiến hành phân tích CV và JD dưới đây theo 4 bước sau:
        1. Rút ra 3-5 yêu cầu quan trọng như kỹ năng, kinh nghiệm từ JD.
        2. Tìm điểm chung cụ thể trong CV khớp với từng yêu cầu của JD.
        3. Ghi nhận những điểm mạnh và điểm yếu.
        4. Dựa trên phân tích ở bước 3, hãy cho một điểm số duy nhất từ 0 đến 100.

        Hãy trả về kết quả dưới dạng một chuỗi json hợp lệ và không có gì khác.
        JSON object phải có dạng: {{"score": <số_nguyên>}}


        --- JD ---
        {jd_text}
        
        --- CV ---
        {cv_text}
        """

        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Bạn là một AI chỉ trả lời bằng định dạng JSON."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.0 
        )
        response_content = chat_completion.choices[0].message.content
        
        json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            ai_result = json.loads(json_str)
            score = int(ai_result.get("score", 0))
        else:
            numbers = re.findall(r'\d+', response_content)
            score = int(numbers[-1]) if numbers else 0
        
        return score

    except Exception as e:
        print(f"Lỗi khi lấy điểm AI: {e}")
        print(f"Nội dung AI trả về (gây lỗi): {response_content}")
        return 0 
    
def job_list_view(request):
    if request.user.is_authenticated:
        if request.user.user_type == 'recruiter':
            return redirect('recruiter_dashboard')
        else:
            return redirect('job_board') 

    jobs = JobPosting.objects.filter(is_archived=False).select_related('recruiter__profile')

    query = request.GET.get('q', '')
    location = request.GET.get('location', '')
    category = request.GET.get('category', '')

    if query:
        jobs = jobs.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )
    
    if location:
        jobs = jobs.filter(location__icontains=location)
        
    if category:
        jobs = jobs.filter(category=category)

    context = {
        'jobs': jobs.order_by('-created_at'),
        'categories': JobPosting.CATEGORY_CHOICES,
        'provinces': VIETNAM_PROVINCES,
        'search_values': request.GET
    }
    return render(request, 'recruitment/job_list.html', context)

def login_view(request):
    if request.user.is_authenticated:
        return redirect('job_list') 

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            if user.user_type == 'recruiter':
                return redirect('recruiter_dashboard')
            else:
                return redirect('job_board')
    else:
        form = AuthenticationForm()

    form.fields['username'].widget.attrs.update(
        {'class': 'form-control', 'placeholder': 'Nhập tên đăng nhập của bạn'}
    )
    form.fields['password'].widget.attrs.update(
        {'class': 'form-control', 'placeholder': 'Nhập mật khẩu'}
    )
    
    return render(request, 'registration/login.html', {'form': form})

@login_required
def job_board_view(request):
    if request.user.user_type != 'candidate':
        return redirect('recruiter_dashboard') 

    jobs = JobPosting.objects.filter(is_archived=False).select_related('recruiter__profile')
    query = request.GET.get('q', '')
    location = request.GET.get('location', '')
    category = request.GET.get('category', '')
    
    if query:
        jobs = jobs.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )
    
    if location:
        jobs = jobs.filter(location__icontains=location)
        
    if category:
        jobs = jobs.filter(category=category)

    context = {
        'jobs': jobs.order_by('-created_at'),
        'categories': JobPosting.CATEGORY_CHOICES, 
        'provinces': VIETNAM_PROVINCES,
        'search_values': request.GET 
    }
    return render(request, 'recruitment/job_board.html', context)

@login_required
def view_candidate_profile(request, user_id):

    if request.user.user_type != 'recruiter':
        messages.error(request, "Bạn không có quyền truy cập trang này.")
        return redirect('job_list')

    profile_user = get_object_or_404(CustomUser, id=user_id, user_type='candidate')
    profile = get_object_or_404(Profile, user=profile_user)

    applications = Application.objects.filter(
        candidate=profile_user,
        job__recruiter=request.user
    ).select_related('job').order_by('-applied_at')

    context = {
        'profile': profile,
        'applications': applications 
    }
    return render(request, 'recruitment/view_candidate_profile.html', context)

def logout_view(request):
    logout(request)
    messages.success(request, "Bạn đã đăng xuất thành công.")
    return redirect('job_list')

@login_required
def process_application_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, job__recruiter=request.user)
    
    if request.method == 'POST':
        decision = request.POST.get('decision') 
        custom_message = request.POST.get('custom_message', '')
        is_talent_pool = request.POST.get('is_talent_pool') == 'on'

        candidate_profile, _ = Profile.objects.get_or_create(user=application.candidate)
        candidate_name = candidate_profile.full_name or application.candidate.username
        job_title = application.job.title
        recruiter_profile, _ = Profile.objects.get_or_create(user=request.user)
        recruiter_name = recruiter_profile.full_name or request.user.username

        combined_interview_datetime_obj = None 
        new_status = ""
        success_message = ""
        template_type = ""

        try:
            combined_interview_time_for_ai = ""

            if decision == 'invite':
                interview_time_str = request.POST.get('interview_time')
                interview_date_str = request.POST.get('interview_date')
                interview_location = request.POST.get('interview_location', '')
                
                try:
                    combined_datetime_str = f"{interview_date_str} {interview_time_str}"
                    combined_interview_datetime_obj = datetime.datetime.strptime(combined_datetime_str, '%Y-%m-%d %H:%M')
                    
                    formatted_date = combined_interview_datetime_obj.strftime('%d/%m/%Y lúc %H:%M')
                    combined_interview_time_for_ai = formatted_date
                except (ValueError, TypeError):
                    combined_interview_time_for_ai = f"{interview_time_str} {interview_date_str}"

                template_type = 'invite'
                new_status = 'invited'
                success_message = f"Đã gửi lời mời phỏng vấn đến {candidate_name}."

            elif decision == 'reject_cv':
                template_type = 'reject_cv'
                new_status = 'rejected'
                success_message = f"Đã gửi thông báo từ chối (lọc CV) đến {candidate_name}."
                application.is_talent_pool = is_talent_pool # <-- LƯU KHO NHÂN TÀI

            elif decision == 'pass':
                template_type = 'pass'
                new_status = 'passed'
                success_message = f"Đã gửi thông báo trúng tuyển đến {candidate_name}."

            elif decision == 'reject_interview':
                template_type = 'reject_interview'
                new_status = 'rejected'
                success_message = f"Đã gửi thông báo từ chối (rớt PV) đến {candidate_name}."
                application.is_talent_pool = is_talent_pool # <-- LƯU KHO NHÂN TÀI
            
            else:
                messages.error(request, 'Lựa chọn không hợp lệ.')
                return redirect('process_application', application_id=application.id)
            
            template_obj = EmailTemplate.objects.get(recruiter=request.user, template_type=template_type)
            template_context = Context({
                'candidate_name': candidate_name,
                'job_title': job_title,
                'recruiter_name': recruiter_name,
                'custom_message': custom_message,
                'interview_time': combined_interview_time_for_ai,
                'interview_location': request.POST.get('interview_location', ''),
            })
            email_content = Template(template_obj.content).render(template_context)
            
            action_url = None
            if decision == 'invite':
                action_url = request.build_absolute_uri(
                    reverse('confirm_interview', kwargs={'application_id': application.id})
                )
            
            Notification.objects.create(
                recipient=application.candidate,
                message=email_content,
                action_url=action_url 
            )
            
            application.status = new_status
            application.save()

            if decision == 'invite' and combined_interview_datetime_obj:
                interview, created = Interview.objects.get_or_create(application=application)
                interview.interview_date = combined_interview_datetime_obj
                interview.location = request.POST.get('interview_location', '')
                interview.save()
            
            messages.success(request, success_message)

        except EmailTemplate.DoesNotExist:
            messages.error(request, f"Không tìm thấy mẫu email cho '{decision}'. Vui lòng tạo mẫu trong 'Quản lý Mẫu Email' trước.")
        except Exception as e:
            print(f"Lỗi khi xử lý hồ sơ (dùng template): {e}")
            messages.error(request, 'Đã có lỗi xảy ra. Không thể gửi thông báo.')

        return redirect('applicant_list', job_id=application.job.id)

    else:
        templates = {}
        relevant_templates = ['invite', 'reject_cv', 'pass', 'reject_interview']
        for t_type in relevant_templates:
            template_obj, created = EmailTemplate.objects.get_or_create(
                recruiter=request.user,
                template_type=t_type,
                defaults={'content': DEFAULT_TEMPLATES.get(t_type, '')}
            )
            templates[t_type] = template_obj.content
        
        context = {
            'application': application,
            'current_status': application.status,
            'templates_json': json.dumps(templates), 
        }
        return render(request, 'recruitment/process_application.html', context)
    
@login_required
def chat_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id)

    if not (request.user == application.candidate or request.user == application.job.recruiter):
        messages.error(request, "Bạn không có quyền truy cập cuộc trò chuyện này.")
        return redirect('job_list')

    if request.user == application.candidate:
        recipient = application.job.recruiter
    else:
        recipient = application.candidate

    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
           
            DirectMessage.objects.create(
                application=application,
                sender=request.user,
                recipient=recipient,
                content=content,
                is_read=False 
            )
            messages.success(request, "Đã gửi tin nhắn.")
        
        return redirect('chat_view', application_id=application_id)

    messages_list = DirectMessage.objects.filter(application=application)
    messages_list.filter(recipient=request.user, is_read=False).update(is_read=True)
    
    context = {
        'application': application,
        'messages': messages_list,
        'hide_messages': True,
    }
    return render(request, 'recruitment/chat_page.html', context)

@login_required
def my_applications_view(request):
    if request.user.user_type != 'candidate':
        return redirect('recruiter_dashboard') 

    applications = Application.objects.filter(
        candidate=request.user
    ).select_related(
        'job', 'job__recruiter'
    ).order_by('-applied_at')
    
    context = {
        'applications': applications
    }
    return render(request, 'recruitment/my_applications.html', context)

@login_required
def my_messages_view(request):
    applications_with_messages = Application.objects.filter(
        Q(candidate=request.user) | Q(job__recruiter=request.user),
        Exists(DirectMessage.objects.filter(application=OuterRef('pk')))
    ).annotate(
        last_message_time=Max('messages__timestamp'),
        unread_count=Count('messages', filter=Q(messages__recipient=request.user, messages__is_read=False))
        
    ).order_by('-last_message_time') 
    
    context = {
        'applications_with_messages': applications_with_messages
    }
    return render(request, 'recruitment/my_messages.html', context)

@login_required
def clone_job_view(request, job_id):
    original_job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    original_job.pk = None
    original_job.id = None
    original_job._state.adding = True 
    original_job.title = f"{original_job.title}"
    original_job.created_at = timezone.now() 
    original_job.is_archived = False
    original_job.save()
    
    new_job_id = original_job.pk 
    
    messages.success(request, f"Đã tạo bản sao tin tuyển dụng. Bạn có thể chỉnh sửa và đăng ngay.")
    
    return redirect('edit_job', job_id=new_job_id)

@login_required
def archived_job_list_view(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list') 

    archived_jobs = JobPosting.objects.filter(
        recruiter=request.user, 
        is_archived=True
    ).order_by('-created_at')
    
    context = {
        'jobs': archived_jobs
    }
    return render(request, 'recruitment/archived_job_list.html', context)

@login_required
def hard_delete_job_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user, is_archived=True)
    
    if request.method == 'POST':
        job_title = job.title
        job.delete() 
        
        messages.success(request, f'Đã xóa vĩnh viễn tin tuyển dụng "{job_title}".')
        return redirect('archived_job_list') 
    
    return render(request, 'recruitment/hard_delete_job_confirm.html', {'job': job})

@login_required
def application_result_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, candidate=request.user)
    
    analysis_result = request.session.get('analysis_result', None)
    
    if 'analysis_result' in request.session:
        del request.session['analysis_result']

    context = {
        'application': application,
        'analysis': analysis_result 
    }
    return render(request, 'recruitment/application_result.html', context)

@login_required
def manage_templates_view(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list')
    
    if request.method == 'POST':
        template_type = request.POST.get('template_type')
        content = request.POST.get('content')
        
        template_obj = get_object_or_404(
            EmailTemplate, 
            recruiter=request.user, 
            template_type=template_type
        )
        template_obj.content = content
        template_obj.save()
        messages.success(request, f"Đã cập nhật mẫu '{template_obj.get_template_type_display()}' thành công.")
        return redirect('manage_templates')

    templates = {}
    for key, default_content in DEFAULT_TEMPLATES.items():
        template_obj, created = EmailTemplate.objects.get_or_create(
            recruiter=request.user,
            template_type=key,
            defaults={'content': default_content}
        )
        templates[key] = template_obj
        
    return render(request, 'recruitment/manage_templates.html', {'templates': templates})

@login_required
def all_applicants_view(request):
    """
    TRANG GỘP (ĐÃ VIẾT LẠI):
    - Xử lý GET: Lọc và sắp xếp danh sách Ứng tuyển.
    - Xử lý POST: Tìm kiếm AI trên danh sách Ứng tuyển.
    - Cả hai đều trả về MỘT danh sách 'applications' duy nhất.
    """
    
    status_choices = Application.STATUS_CHOICES
    
    base_applications_query = Application.objects.filter(
        job__recruiter=request.user,
        job__is_archived=False
    ).select_related('job', 'candidate__profile')

    is_search_results = False 
    query = "" 

    if request.method == 'POST':
        query = request.POST.get('query', '')
        is_search_results = True 
        
        if query:
            all_applications_data = []
            for app in base_applications_query:
                cv_text = extract_text_from_cv(app.cv)
                if cv_text:
                    all_applications_data.append({
                        "application_id": app.id, 
                        "cv_text": cv_text
                    })

            if not all_applications_data:
                applications = base_applications_query.none()
            else:
                applications_json_str = json.dumps(all_applications_data, ensure_ascii=False)
                prompt = f"""Với vai trò là headhunter, hãy phân tích yêu cầu sau đây và tìm 3 HỒ SƠ ỨNG TUYỂN phù hợp nhất từ danh sách.
                YÊU CẦU: {query}
                DANH SÁCH HỒ SƠ ỨNG TUYỂN: {applications_json_str}
                
                Hãy trả về MỘT CHUỖI JSON HỢP LỆ. Chuỗi JSON là một danh sách (list), mỗi phần tử là một object chỉ có 2 key: "application_id" (số nguyên) và "reason" (chuỗi giải thích ngắn gọn)."""
                
                try:
                    client = groq.Groq(api_key=settings.GROQ_API_KEY)
                    chat_completion = client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": "Bạn là một AI chuyên tìm kiếm, chỉ trả về kết quả dưới dạng JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        model="llama-3.1-8b-instant" 
                    )
                    response_text = chat_completion.choices[0].message.content
                    
                    json_str = response_text
                    json_match_markdown = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
                    
                    if json_match_markdown:
                        json_str = json_match_markdown.group(1)
                    else:
                        json_match_plain = re.search(r'[\{\[].*?[\}\]]', response_text, re.DOTALL)
                        if json_match_plain:
                            json_str = json_match_plain.group(0)
                    
                    ai_results = json.loads(json_str)
                    
                    application_ids = [res.get("application_id") for res in ai_results]
                    applications = base_applications_query.filter(id__in=application_ids)
                    
                except Exception as e:
                    print(f"Lỗi Groq API khi tìm kiếm ứng viên: {e}")
                    messages.error(request, 'Đã có lỗi xảy ra với AI. Vui lòng thử lại.')
                    applications = base_applications_query.none() 
        else:
            applications = base_applications_query.none()

    else:
        sort_by = request.GET.get('sort', '-applied_at')
        status_filter = request.GET.get('status', '')

        valid_sorts = ['-applied_at', 'applied_at', '-ai_score']
        if sort_by not in valid_sorts:
            sort_by = '-applied_at'
        
        filtered_applications_query = base_applications_query
        if status_filter:
            filtered_applications_query = filtered_applications_query.filter(status=status_filter)

        applications = filtered_applications_query.order_by(sort_by)

    context = {
        'applications': applications,
        'status_choices': status_choices,
        'query': query, 
        'is_search_results': is_search_results 
    }
    return render(request, 'recruitment/all_applicants_list.html', context)

@login_required
def application_detail_view(request, application_id):
    if request.user.user_type != 'recruiter':
        messages.error(request, "Bạn không có quyền truy cập trang này.")
        return redirect('job_list')
        
    application = get_object_or_404(
        Application.objects.select_related('job', 'candidate__profile'),
        pk=application_id,
        job__recruiter=request.user 
    )

    context = {
        'application': application,
        'profile': application.candidate.profile,
        'job': application.job
    }
    return render(request, 'recruitment/application_detail.html', context)