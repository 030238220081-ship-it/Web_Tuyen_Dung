import json, fitz, docx, groq, random, re, traceback
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, login
from .models import JobPosting, Application, Profile, Notification, Interview, Question, Answer, QuizResult, EssayAnswer
from .forms import CustomUserCreationForm, ProfileForm
from django.urls import reverse_lazy
from django.views import generic
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Avg
from django.urls import reverse
from django.http import JsonResponse
from .utils import extract_text_from_cv
from django.core.serializers.json import DjangoJSONEncoder
from django.contrib.auth.forms import AuthenticationForm

CustomUser = get_user_model()

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

def job_list(request):
    jobs = JobPosting.objects.all().order_by('-created_at')
    return render(request, 'recruitment/job_list.html', {'jobs': jobs})

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

        # Lưu kết quả nháp vào session
        request.session['jd_title'] = title
        request.session['generated_jd'] = generated_jd.strip()

        # Chuyển hướng đến trang chỉnh sửa
        return redirect('create_job_review')

    return render(request, 'recruitment/create_job.html')

@login_required
def job_detail(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id)
    if request.method == 'POST' and request.user.user_type == 'candidate':
        cv_file = request.FILES.get('cv')
        if not cv_file:
            return redirect('job_detail', job_id=job_id)
        cv_text = extract_text_from_cv(cv_file)
        if not cv_text:
            return redirect('job_detail', job_id=job_id)

        prompt = f"""Phân tích JD và CV dưới đây.
        JD: {job.description}
        CV: {cv_text}
        Hãy trả về kết quả là MỘT CHUỖI JSON HỢP LỆ và KHÔNG có bất kỳ văn bản nào khác. JSON object phải có 2 key: "score" (số nguyên từ 0-100) và "summary" (tóm tắt 3 điểm mạnh nhất)."""
        
        ai_score, ai_summary = 0, "Không thể phân tích."
        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Bạn là một AI chuyên sàng lọc CV, chỉ trả về kết quả dưới dạng JSON."},
                    {"role": "user", "content": prompt}
                ],
                model="llama-3.3-70b-versatile",
            )
            response_text = chat_completion.choices[0].message.content
            ai_result = json.loads(response_text)
            ai_score = ai_result.get('score', 0)
            ai_summary = ai_result.get('summary', 'Lỗi tóm tắt.')
        except Exception as e:
            print(f"Lỗi Groq API khi sàng lọc CV: {e}")

        Application.objects.create(job=job, candidate=request.user, cv=cv_file, ai_score=ai_score, ai_summary=ai_summary)
        messages.success(request, 'Bạn đã nộp hồ sơ thành công!')
        return redirect('job_list')
    return render(request, 'recruitment/job_detail.html', {'job': job})

@login_required
def analyze_cv_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id)
    profile, created = Profile.objects.get_or_create(user=request.user)
    if not profile.cv_file:
        return render(request, 'recruitment/analysis_result.html', {'error': 'Bạn cần tải CV lên hồ sơ trước.'})
    cv_text = extract_text_from_cv(profile.cv_file)
    if not cv_text:
        return render(request, 'recruitment/analysis_result.html', {'error': 'Không đọc được file CV.'})

    prompt = f"""Phân tích sự phù hợp giữa CV và JD.
    JD: {job.description}
    CV: {cv_text}
    Hãy trả về 3 điểm: 1. Mức độ phù hợp (%), 2. 3 điểm mạnh nhất, 3. 2 điểm cần cải thiện."""
    
    analysis_result = "Không thể phân tích."
    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        analysis_result = chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Lỗi Groq API khi phân tích CV: {e}")

    return render(request, 'recruitment/analysis_result.html', {'result': analysis_result, 'job': job})

@login_required
def generate_interview_questions(request, application_id):
    application = get_object_or_404(Application, pk=application_id, job__recruiter=request.user)
    cv_text = extract_text_from_cv(application.cv)
    job_description = application.job.description
    if not cv_text:
        return render(request, 'recruitment/interview_questions.html', {'error': 'Không thể đọc file CV của ứng viên.'})

    prompt = f"""Với vai trò là một người quản lý tuyển dụng, hãy dựa vào JD và CV của ứng viên dưới đây.
    --- JD ---
    {job_description}
    --- END JD ---
    --- CV ---
    {cv_text}
    --- END CV ---
    Hãy tạo ra một danh sách gồm 5 câu hỏi phỏng vấn sâu sắc để đánh giá năng lực và sự phù hợp của ứng viên này.
    """
    
    interview_questions = "Không thể tạo câu hỏi."
    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        interview_questions = chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Lỗi Groq API khi tạo câu hỏi phỏng vấn: {e}")

    context = {'application': application, 'questions': interview_questions}
    return render(request, 'recruitment/interview_questions.html', context)

@login_required
def chat_api_view(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user_message = data.get('message')
        prompt = f"""Bạn là một trợ lý tuyển dụng AI thân thiện tên là JobAI. Hãy trả lời câu hỏi của ứng viên một cách ngắn gọn, hữu ích. Câu hỏi: "{user_message}" """
        
        bot_response = "Lỗi kết nối đến AI."
        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
            )
            bot_response = chat_completion.choices[0].message.content
        except Exception as e:
            print(f"Lỗi Groq API (Chatbot): {e}")

        return JsonResponse({'response': bot_response.strip()})
    return JsonResponse({'error': 'Invalid request method'}, status=405)

@login_required
def search_candidates_view(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list')
    results = []
    query = ""
    if request.method == 'POST':
        query = request.POST.get('query', '')
        if query:
            candidate_profiles = Profile.objects.filter(user__user_type='candidate').exclude(cv_file__isnull=True).exclude(cv_file__exact='')
            all_candidates_data = []
            for profile in candidate_profiles:
                cv_text = extract_text_from_cv(profile.cv_file)
                if cv_text:
                    all_candidates_data.append({
                        "user_id": profile.user.id,
                        "cv_text": cv_text
                    })

            candidates_json_str = json.dumps(all_candidates_data, ensure_ascii=False)
            prompt = f"""Với vai trò là headhunter, hãy phân tích yêu cầu sau đây và tìm 3 ứng viên phù hợp nhất từ danh sách CV.
            YÊU CẦU: {query}
            DANH SÁCH CV: {candidates_json_str}
            Hãy trả về MỘT CHUỖI JSON HỢP LỆ và không có gì khác. Chuỗi JSON là một danh sách (list), mỗi phần tử là một object ứng viên có các key: "user_id" (số nguyên), "score" (số nguyên 0-100), "reason" (chuỗi giải thích ngắn gọn)."""
            
            try:
                client = groq.Groq(api_key=settings.GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Bạn là một AI chuyên tìm kiếm ứng viên, chỉ trả về kết quả dưới dạng JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    model="llama-3.3-70b-versatile",
                )
                response_text = chat_completion.choices[0].message.content
                ai_results = json.loads(response_text)
                
                for result in ai_results:
                    try:
                        user = CustomUser.objects.get(pk=result.get("user_id"))
                        profile = Profile.objects.get(user=user)
                        results.append({
                            "user": user,
                            "profile": profile,
                            "score": result.get("score"),
                            "reason": result.get("reason")
                        })
                    except (CustomUser.DoesNotExist, Profile.DoesNotExist):
                        continue
                results.sort(key=lambda x: x['score'], reverse=True)
            except Exception as e:
                print(f"Lỗi Groq API khi tìm kiếm ứng viên: {e}")
                messages.error(request, 'Đã có lỗi xảy ra với AI. Vui lòng thử lại.')

    context = {'results': results, 'query': query}
    return render(request, 'recruitment/search_candidates.html', context)

class RegisterView(generic.CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy('job_list')
    template_name = 'registration/register.html' 

    def form_valid(self, form):
        user = form.save(commit=False)
        user.user_type = 'candidate'
        user.save()
        login(self.request, user)
        return redirect(self.get_success_url())
    
@login_required
def profile_view(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Hồ sơ của bạn đã được cập nhật thành công!')
            return redirect('profile')
    else:
        form = ProfileForm(instance=profile)
    return render(request, 'recruitment/profile.html', {'form': form})

@login_required
def recruiter_dashboard(request):
    if request.user.user_type != 'recruiter':
        return redirect('job_list')
    jobs = JobPosting.objects.filter(recruiter=request.user).annotate(
        application_count=Count('application')
    ).order_by('-created_at')
    total_jobs_posted = jobs.count()
    total_applications_received = sum(job.application_count for job in jobs)
    context = {
    'jobs': jobs,  # Danh sách các job đã được annotate
    'total_jobs_posted': total_jobs_posted,
    'total_applications_received': total_applications_received,
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
    """
    View này chỉ có nhiệm vụ hiển thị trang chatbot.
    """
    return render(request, 'recruitment/chatbot.html')

@login_required
def job_match_view(request):
    profile = request.user.profile
    
    if not profile.cv_file:
        context = {'has_cv': False}
        return render(request, 'recruitment/job_matches.html', context)

    try:
        cv_text = extract_text_from_cv(profile.cv_file)
        if not cv_text:
            context = {'error_message': 'Không thể đọc được nội dung từ file CV của bạn.'}
            return render(request, 'recruitment/job_matches.html', context)

        # === DÒNG GỠ RỐI 1: KIỂM TRA NỘI DUNG CV ===
        print("\n--- BẮT ĐẦU PHÂN TÍCH TÌM VIỆC ---")
        print(f"NỘI DUNG CV ĐÃ ĐỌC (50 ký tự đầu): {cv_text[:50]}...")
        print("------------------------------------")

        all_jobs = JobPosting.objects.all()
        matched_jobs_with_scores = []

        for job in all_jobs:
            print(f"Đang phân tích Job: '{job.title}'")
            score = get_ai_match_score(cv_text, job.description)
            
            # === DÒNG GỠ RỐI 2: XEM ĐIỂM SỐ CỤ THỂ ===
            print(f"-> Điểm AI trả về: {score}") 
            
            if score > 20:
                job.match_score = score
                matched_jobs_with_scores.append(job)
                print("-> KẾT QUẢ: Job được thêm vào danh sách.")
            else:
                print("-> KẾT QUẢ: Job bị loại do điểm thấp.")
            print("---") # In ra để phân tách các job

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
        return redirect('job_matches')

    if not profile.cv_file:
        messages.error(request, 'Bạn chưa có CV trong hồ sơ để ứng tuyển.')
        return redirect('profile')

    Application.objects.create(
        job=job, 
        candidate=request.user, 
        cv=profile.cv_file,
        ai_score=0,
        ai_summary="Ứng tuyển nhanh bằng hồ sơ có sẵn."
    )

    messages.success(request, f'Bạn đã ứng tuyển thành công vào vị trí "{job.title}"!')
    return redirect('job_matches')

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
        'generated_jd': generated_jd
    }
    return render(request, 'recruitment/create_job_review.html', context)

@login_required
def delete_job_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    
    if request.method == 'POST':
        job_title = job.title
        job.delete()
        messages.success(request, f'Đã xóa thành công tin tuyển dụng "{job_title}".')
        return redirect('recruiter_dashboard')
    
    return render(request, 'recruitment/delete_job_confirm.html', {'job': job})

@login_required
def edit_job_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    if request.method == 'POST':
        job.title = request.POST.get('title', job.title)
        job.location = request.POST.get('location')
        job.salary = request.POST.get('salary')
        job.quantity = request.POST.get('quantity')
        job.benefits = request.POST.get('benefits')
        job.description = request.POST.get('description', job.description)
        job.save()
        messages.success(request, f'Đã cập nhật thành công tin tuyển dụng "{job.title}".')
        return redirect('recruiter_dashboard')
    context = {'job': job}
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
            model="llama-3.3-70b-versatile",
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
def send_interview_invitation_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, job__recruiter=request.user)


    if QuizResult.objects.filter(application=application).exists():
        messages.warning(request, f"Ứng viên {application.candidate.username} đã hoàn thành bài trắc nghiệm.")
        return redirect('applicant_list', job_id=application.job.id)

    if not application.job.questions.exists():
        messages.error(request, f"Bạn cần tạo bộ câu hỏi trắc nghiệm cho vị trí '{application.job.title}' trước khi gửi lời mời.")
        return redirect('applicant_list', job_id=application.job.id)

    quiz_url = reverse('take_quiz', kwargs={'application_id': application.id})

    # Tạo thông báo cho ứng viên
    message_content = f"Nhà tuyển dụng '{request.user.username}' mời bạn thực hiện bài trắc nghiệm sàng lọc cho vị trí '{application.job.title}'. Bấm vào đây để bắt đầu."
    Notification.objects.create(
        recipient=application.candidate,
        message=message_content,
        action_url=quiz_url  # Lưu URL vừa tạo
    )

    messages.success(request, f"Đã gửi lời mời làm trắc nghiệm đến ứng viên {application.candidate.username}.")
    return redirect('applicant_list', job_id=application.job.id)

@login_required
def notification_list_view(request):
    notifications = Notification.objects.filter(recipient=request.user)
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return render(request, 'recruitment/notifications.html', {'notifications': notifications})

@login_required
def conduct_interview_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, job__recruiter=request.user)

    # Xử lý khi HR nhập ghi chú và yêu cầu AI phân tích
    if request.method == 'POST':
        hr_notes = request.POST.get('hr_notes')

        cv_text = extract_text_from_cv(application.cv)
        jd_text = application.job.description

        analysis_prompt = f"""Bạn là một chuyên gia nhân sự dày dặn kinh nghiệm. Dựa vào JD, CV, và ghi chú phỏng vấn dưới đây, hãy đưa ra một bản phân tích toàn diện.

        --- JD ---
        {jd_text}
        --- CV ---
        {cv_text}
        --- GHI CHÚ PHỎNG VẤN (câu hỏi của HR và câu trả lời của ứng viên) ---
        {hr_notes}

        Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác. JSON phải có 3 key:
        - "score": Điểm số tổng thể (số nguyên từ 0-100) dựa trên sự phù hợp.
        - "strengths": Một danh sách (list) chứa 3 chuỗi, mỗi chuỗi là một điểm mạnh chính của ứng viên được thể hiện qua buổi phỏng vấn.
        - "weaknesses": Một danh sách (list) chứa 2 chuỗi, mỗi chuỗi là một điểm yếu hoặc điều cần cải thiện.
        """

        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": analysis_prompt}],
                model="llama-3.3-70b-versatile", # Dùng model mạnh nhất
            )
            response_text = chat_completion.choices[0].message.content
            ai_analysis_data = json.loads(response_text)

            # Lưu kết quả vào model Interview
            Interview.objects.update_or_create(
                application=application,
                defaults={
                    'hr_notes': hr_notes,
                    'ai_analysis': ai_analysis_data,
                    'ai_score': ai_analysis_data.get('score', 0)
                }
            )
            messages.success(request, "Đã phân tích và lưu kết quả phỏng vấn thành công!")
        except Exception as e:
            print(f"Lỗi API khi phân tích phỏng vấn: {e}")
            messages.error(request, "AI gặp sự cố, không thể phân tích buổi phỏng vấn.")

        return redirect('applicant_list', job_id=application.job.id)

    questions_prompt = f"""Dựa vào JD và CV dưới đây, hãy tạo ra 5 câu hỏi phỏng vấn sâu sắc để đánh giá năng lực và sự phù hợp của ứng viên.
    --- JD ---
    {application.job.description}
    --- CV ---
    {extract_text_from_cv(application.cv)}
    """
    suggested_questions = "Không thể tạo câu hỏi gợi ý."
    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": questions_prompt}],
            model="llama-3.3-70b-versatile", # Dùng model nhanh để gợi ý
        )
        suggested_questions = chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Lỗi API khi tạo câu hỏi PV: {e}")

    context = {
        'application': application,
        'suggested_questions': suggested_questions,
    }
    return render(request, 'recruitment/conduct_interview.html', context)

@login_required
def generate_quiz_view(request, job_id):
    job = get_object_or_404(JobPosting, pk=job_id, recruiter=request.user)
    job.questions.all().delete()

    prompt = f"""Bạn là một chuyên gia tuyển dụng kỹ thuật. Dựa vào Mô tả công việc (JD) dưới đây, hãy tạo một bài kiểm tra sàng lọc ngắn.

    --- JD ---
    {job.description}

    Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác. Toàn bộ chuỗi JSON phải được bọc trong cặp dấu ```json ... ```.
    KHÔNG GIẢI THÍCH GÌ THÊM. JSON object phải có 2 key:
    1. "multiple_choice": Một danh sách (list) chứa 3 câu hỏi trắc nghiệm ở mức độ trung bình-khó. Mỗi câu hỏi là một object có:
        - "question": (string) Nội dung câu hỏi.
        - "answers": (list) Một danh sách gồm 4 chuỗi đáp án KHÁC NHAU. Đáp án ĐÚNG phải luôn nằm ở vị trí đầu tiên.
    2. "essay": Một danh sách (list) chứa 2 câu hỏi tự luận tình huống, yêu cầu ứng viên giải thích cách xử lý một vấn đề thực tế liên quan đến công việc.
    """
    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
        )
        response_text = chat_completion.choices[0].message.content

        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text 

        quiz_data = json.loads(json_str)

        for item in quiz_data.get('multiple_choice', []):
            q = Question.objects.create(job_posting=job, text=item['question'], question_type='MC')
            correct_answer_text = item['answers'][0]
            all_answers = item['answers']
            random.shuffle(all_answers)
            for answer_text in all_answers:
                Answer.objects.create(question=q, text=answer_text, is_correct=(answer_text == correct_answer_text))

        # Tạo câu hỏi tự luận
        for question_text in quiz_data.get('essay', []):
            Question.objects.create(job_posting=job, text=question_text, question_type='ESSAY')

        messages.success(request, f"Đã tạo thành công bộ câu hỏi sàng lọc cho vị trí '{job.title}'.")

    # Bắt lỗi cụ thể hơn
    except json.JSONDecodeError:
        messages.error(request, "AI đã trả về dữ liệu không hợp lệ. Vui lòng thử lại.")
        print("--- LỖI JSON ---")
        print(response_text) # In ra phản hồi lỗi để bạn gỡ rối
        print("-----------------")
    except Exception as e:
        print(f"Lỗi API khi tạo quiz: {e}")
        messages.error(request, "AI gặp sự cố, không thể tạo bộ câu hỏi.")

    return redirect('recruiter_dashboard')

@login_required
def take_quiz_view(request, application_id):
    application = get_object_or_404(Application, pk=application_id, candidate=request.user)
    if QuizResult.objects.filter(application=application).exists():
        messages.warning(request, "Bạn đã hoàn thành bài trắc nghiệm cho vị trí này rồi.")
        return redirect('job_list') 
    questions = application.job.questions.all()

    if not questions.exists():
        messages.error(request, "Nhà tuyển dụng chưa tạo bộ câu hỏi cho vị trí này.")
        return redirect('job_list')

    mc_questions = application.job.questions.filter(question_type='MC')
    essay_questions = application.job.questions.filter(question_type='ESSAY')

    if request.method == 'POST':
        correct_answers = 0
        for question in mc_questions:
            selected_answer_id = request.POST.get(f'question_{question.id}')
            if selected_answer_id:
                selected_answer = Answer.objects.get(pk=selected_answer_id)
                if selected_answer.is_correct:
                    correct_answers += 1

        score = (correct_answers / mc_questions.count()) * 100 if mc_questions.count() > 0 else 0
        QuizResult.objects.create(
            application=application, score=score,
            correct_answers=correct_answers, total_questions=mc_questions.count()
        )

        for question in essay_questions:
            answer_text = request.POST.get(f'question_{question.id}')
            if answer_text:
                EssayAnswer.objects.create(
                    application=application, question=question, answer_text=answer_text
                )

        messages.success(request, "Bạn đã hoàn thành bài kiểm tra. Kết quả đã được gửi đến nhà tuyển dụng.")
        return redirect('job_list')

    context = {
        'application': application, 
        'mc_questions': mc_questions, 
        'essay_questions': essay_questions,
        'time_limit': application.job.time_limit 
    }
    return render(request, 'recruitment/take_quiz.html', context)

# recruitment/views.py

@login_required
def cv_review_view(request):
    # Xử lý khi người dùng gửi yêu cầu phân tích (POST request)
    if request.method == 'POST':
        response_text = ""
        try:
            # Phần lấy CV và JD giữ nguyên, không thay đổi
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
            
            # === BƯỚC 1: LẤY ĐIỂM SỐ NHẤT QUÁN TỪ HÀM CHUNG ===
            score = get_ai_match_score(cv_text, jd_text)

            # === BƯỚC 2: DÙNG ĐIỂM SỐ LÀM NGỮ CẢNH ĐỂ LẤY PHÂN TÍCH CHI TIẾT ===
            analysis_prompt = f"""
            Một ứng viên có CV đạt {score} điểm (trên thang 100) khi so sánh với một Mô tả công việc (JD).
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
                model="llama-3.3-70b-versatile",
            )
            response_text = chat_completion.choices[0].message.content
            
            # Phần xử lý JSON (giữ nguyên)
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text
            analysis_data = json.loads(json_str)

            # === TỔ HỢP KẾT QUẢ ĐỂ GỬI VỀ FRONTEND ===
            # Tự thêm điểm số đã tính ở Bước 1 vào kết quả cuối cùng
            final_response_data = {
                "score": score,
                "strengths": analysis_data.get("strengths", []), # Dùng .get để an toàn
                "suggestions": analysis_data.get("suggestions", [])
            }
            
            return JsonResponse({'success': True, 'data': final_response_data})

        except Exception as e:
            print("--- LỖI NGHIÊM TRỌNG KHI PHÂN TÍCH CV ---")
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': 'Đã có lỗi nghiêm trọng xảy ra phía máy chủ.'})
    
    # Nếu là request GET, chỉ hiển thị trang với danh sách Job (giữ nguyên)
    else:
        all_jobs = JobPosting.objects.all()
        context = {'jobs': all_jobs}
        return render(request, 'recruitment/cv_review.html', context)
    
@login_required
def recruitment_analytics_view(request):
    selected_month = request.GET.get('month', '')
    selected_job_id = request.GET.get('job_id', '')
    recruiter_jobs_query = JobPosting.objects.filter(recruiter=request.user)

    if selected_month:
        recruiter_jobs_query = recruiter_jobs_query.filter(created_at__month=selected_month)
    
    if selected_job_id:
        recruiter_jobs_query = recruiter_jobs_query.filter(id=selected_job_id)

    job_titles_comparison = []
    actual_applications = []
    planned_quantity = []

    for job in recruiter_jobs_query.order_by('title'):
        job_titles_comparison.append(job.title)
        apps_query = job.application.all()
        if selected_month:
            apps_query = apps_query.filter(applied_at__month=selected_month)
        actual_applications.append(apps_query.count())
        planned_quantity.append(job.quantity)

    kpi_percentages = []
    for i in range(len(job_titles_comparison)):
        if planned_quantity[i] > 0:
            percentage = round((actual_applications[i] / planned_quantity[i]) * 100, 1)
        else:
            percentage = 0
        kpi_percentages.append(percentage)

    dynamic_label = "Thực hiện"
    label_parts = []
    if selected_month:
        label_parts.append(f"Tháng {selected_month}")
    if selected_job_id:
        try:
            job_title = JobPosting.objects.get(id=selected_job_id).title
            label_parts.append(job_title)
        except JobPosting.DoesNotExist:
            pass 
    
    if label_parts:
        dynamic_label += f" ({' & '.join(label_parts)})"

    chart_colors = []
    for _ in range(len(job_titles_comparison)):
        r = random.randint(0, 255)
        g = random.randint(0, 255)
        b = random.randint(0, 255)
        chart_colors.append(f'rgba({r}, {g}, {b}, 0.7)')

    all_jobs_for_filter = JobPosting.objects.filter(recruiter=request.user).order_by('title')
    
    context = {
        'job_titles_comparison_json': json.dumps(job_titles_comparison),
        'actual_applications_json': json.dumps(actual_applications),
        'planned_quantity_json': json.dumps(planned_quantity),
        'kpi_percentages_json': json.dumps(kpi_percentages),
        'chart_colors_json': json.dumps(chart_colors),
        'all_jobs_for_filter': all_jobs_for_filter,
        'months': range(1, 13), 
        'selected_month': int(selected_month) if selected_month else None,
        'selected_job_id': int(selected_job_id) if selected_job_id else None,
        'dynamic_label': dynamic_label,
    }
    return render(request, 'recruitment/recruitment_analytics.html', context)

def get_ai_match_score(cv_text, jd_text):
    """
    Hàm chuyên dụng để tính điểm phù hợp giữa CV và JD.
    Chỉ trả về một số nguyên từ 0-100.
    """
    try:
        prompt = f"""
        Phân tích CV và JD sau đây. Trả về MỘT SỐ NGUYÊN DUY NHẤT từ 0 đến 100 thể hiện mức độ phù hợp. 
        KHÔNG GIẢI THÍCH GÌ THÊM. CHỈ TRẢ VỀ CON SỐ.

        --- CV ---
        {cv_text}
        
        --- JD ---
        {jd_text}
        """
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile", 
            temperature=0.1 
        )
        response_content = chat_completion.choices[0].message.content
        score = int(re.search(r'\d+', response_content).group(0))
        return score
    except Exception as e:
        print(f"Lỗi khi lấy điểm AI: {e}")
        return 0 
    
def job_list_view(request):
    """
    Hiển thị landing page cho khách.
    Nếu người dùng đã đăng nhập, chuyển hướng họ đến trang chức năng.
    """
    if request.user.is_authenticated:
        if request.user.user_type == 'recruiter':
            return redirect('recruiter_dashboard')
        else:
            return redirect('job_matches')

    jobs = JobPosting.objects.all().order_by('-created_at')
    context = {'jobs': jobs}
    return render(request, 'recruitment/job_list.html', context)

def login_view(request):
    """
    Xử lý logic cho trang đăng nhập riêng biệt.
    """
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
    """
    Hiển thị trang danh sách việc làm CHỈ dành cho ứng viên đã đăng nhập.
    """
    if request.user.user_type != 'candidate':
        return redirect('recruiter_dashboard') 

    jobs = JobPosting.objects.all().order_by('-created_at')
    context = {'jobs': jobs}
    return render(request, 'recruitment/job_board.html', context)