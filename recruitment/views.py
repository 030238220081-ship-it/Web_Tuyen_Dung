import json, fitz, docx, groq, random, re, traceback, datetime
from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, login, logout
from .models import JobPosting, Application, Profile, Notification, DirectMessage
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
                model="llama-3.1-8b-instant" 
            )
            generated_jd = chat_completion.choices[0].message.content
        except Exception as e:
            print(f"Lỗi Groq API khi tạo JD: {e}")
            messages.error(request, 'AI đang gặp sự cố, vui lòng thử lại.')
            return redirect('create_job')

        request.session['jd_title'] = title
        request.session['generated_jd'] = generated_jd.strip()

        return redirect('create_job_review')

    return render(request, 'recruitment/create_job.html')

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

        # --- BẮT ĐẦU LOGIC AI MỚI ---
        # 1. Lấy điểm (Hàm get_ai_match_score đã được tối ưu)
        ai_score = get_ai_match_score(cv_text, job.description)
        
        # 2. Lấy phân tích chi tiết (Điểm mạnh/yếu)
        analysis_prompt = f"""
        Một ứng viên có CV đạt {ai_score} điểm (trên thang 100) khi so sánh với một Mô tả công việc (JD).
        Dựa trên CV và JD dưới đây, hãy đưa ra phân tích.
        
        --- CV ---
        {cv_text}
        --- JD ---
        {job.description}

        Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác, bọc trong cặp dấu ```json ... ```.
        JSON object chỉ cần có 2 key:
        1. "strengths": (list) 2-3 điểm mạnh cụ thể.
        2. "suggestions": (list) 2-3 gợi ý cải thiện.
        """
        
        ai_summary = "Không thể tạo tóm tắt."
        ai_strengths = []
        ai_suggestions = []

        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": analysis_prompt}],
                model="llama-3.1-8b-instant" # Model ổn định của bạn
            )
            response_text = chat_completion.choices[0].message.content
            
            json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text
                
            analysis_data = json.loads(json_str)
            ai_strengths = analysis_data.get("strengths", ["AI không tìm thấy điểm mạnh."])
            ai_suggestions = analysis_data.get("suggestions", ["AI không có gợi ý cải thiện."])
            # Tạo tóm tắt từ điểm mạnh
            ai_summary = "\n".join(f"- {s}" for s in ai_strengths)

        except Exception as e:
            print(f"Lỗi Groq API khi phân tích (job_detail): {e}")
            ai_summary = "Lỗi khi AI phân tích chi tiết."
        # --- KẾT THÚC LOGIC AI MỚI ---

        # Tạo hồ sơ ứng tuyển
        new_application = Application.objects.create(
            job=job, 
            candidate=request.user, 
            cv=cv_file, 
            ai_score=ai_score, 
            ai_summary=ai_summary # Lưu tóm tắt điểm mạnh
        )
        
        # Lưu kết quả phân tích đầy đủ vào session để trang sau sử dụng
        request.session['analysis_result'] = {
            'score': ai_score,
            'strengths': ai_strengths,
            'suggestions': ai_suggestions
        }
        
        # Cập nhật CV mặc định nếu người dùng chọn
        set_as_default = request.POST.get('set_as_default')
        if set_as_default:
            try:
                profile = request.user.profile
                profile.cv_file = new_application.cv
                profile.save()
            except Profile.DoesNotExist:
                Profile.objects.create(user=request.user, cv_file=new_application.cv)
        
        # Chuyển hướng đến trang kết quả
        return redirect('application_result', application_id=new_application.id)
        
    return render(request, 'recruitment/job_detail.html', {'job': job, 'my_application': my_application})

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
            model="llama-3.1-8b-instant"
        )
        analysis_result = chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Lỗi Groq API khi phân tích CV: {e}")

    return render(request, 'recruitment/analysis_result.html', {'result': analysis_result, 'job': job})

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
                model="llama-3.1-8b-instant"
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
            Hãy trả về MỘT CHUỖI JSON HỢP LỆ và không có gì khác. Chuỗi JSON là một danh sách, mỗi phần tử là một object ứng viên có các key: "user_id" (số nguyên), "score" (số nguyên 0-100), "reason" (chuỗi giải thích ngắn gọn)."""
            
            try:
                client = groq.Groq(api_key=settings.GROQ_API_KEY)
                chat_completion = client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": "Bạn là một AI chuyên tìm kiếm ứng viên, chỉ trả về kết quả dưới dạng JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    model="llama-3.1-8b-instant"
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
    context = {
    'jobs': jobs, 
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
    """
    NÂNG CẤP: Ứng tuyển bằng CV hồ sơ, đồng thời
    CHẠY PHÂN TÍCH AI và chuyển đến trang kết quả.
    """
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

    # --- BẮT ĐẦU LOGIC AI MỚI ---
    # Lấy CV từ hồ sơ và chạy phân tích
    cv_text = extract_text_from_cv(profile.cv_file)
    if not cv_text:
        messages.error(request, 'Không thể đọc được file CV trong hồ sơ của bạn.')
        return redirect('profile')

    # 1. Lấy điểm
    ai_score = get_ai_match_score(cv_text, job.description)
    
    # 2. Lấy phân tích chi tiết (Điểm mạnh/yếu)
    analysis_prompt = f"""
    Một ứng viên có CV đạt {ai_score} điểm (trên thang 100) khi so sánh với một Mô tả công việc (JD).
    Dựa trên CV và JD dưới đây, hãy đưa ra phân tích.
    
    --- CV ---
    {cv_text}
    --- JD ---
    {job.description}

    Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác, bọc trong cặp dấu ```json ... ```.
    JSON object chỉ cần có 2 key:
    1. "strengths": (list) 2-3 điểm mạnh cụ thể.
    2. "suggestions": (list) 2-3 gợi ý cải thiện.
    """
    
    ai_summary = "Không thể tạo tóm tắt."
    ai_strengths = []
    ai_suggestions = []

    try:
        client = groq.Groq(api_key=settings.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": analysis_prompt}],
            model="llama-3.1-8b-instant" # Model ổn định của bạn
        )
        response_text = chat_completion.choices[0].message.content
        
        json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text
            
        analysis_data = json.loads(json_str)
        ai_strengths = analysis_data.get("strengths", ["AI không tìm thấy điểm mạnh."])
        ai_suggestions = analysis_data.get("suggestions", ["AI không có gợi ý cải thiện."])
        ai_summary = "\n".join(f"- {s}" for s in ai_strengths)

    except Exception as e:
        print(f"Lỗi Groq API khi phân tích (apply_with_profile): {e}")
        ai_summary = "Lỗi khi AI phân tích chi tiết."
    # --- KẾT THÚC LOGIC AI MỚI ---

    # Tạo hồ sơ ứng tuyển
    new_application = Application.objects.create(
        job=job, 
        candidate=request.user, 
        cv=profile.cv_file, # Sử dụng CV từ hồ sơ
        ai_score=ai_score,
        ai_summary=ai_summary
    )

    # Lưu kết quả phân tích đầy đủ vào session để trang sau sử dụng
    request.session['analysis_result'] = {
        'score': ai_score,
        'strengths': ai_strengths,
        'suggestions': ai_suggestions
    }

    messages.success(request, f'Bạn đã ứng tuyển thành công vào vị trí "{job.title}"!')
    
    # Chuyển hướng đến trang kết quả (giống như luồng CV mới)
    return redirect('application_result', application_id=new_application.id)

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
    """
    View để ứng viên xác nhận lời mời phỏng vấn.
    """
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
    """
    API mới: Nhận dữ liệu dashboard và trả về phân tích của AI.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            kpi_data = data.get('kpi_data', {})
            funnel_data = data.get('funnel_data', {})

            funnel_str = "\n".join([f"- {label}: {count}" for label, count in funnel_data.items()])

            prompt = f"""
            Bạn là một chuyên gia phân tích dữ liệu tuyển dụng (HR Analyst).
            Dưới đây là các số liệu từ dashboard tuyển dụng của tôi.
            
            Số liệu tổng quan:
            - Tổng hồ sơ nhận được: {kpi_data.get('total_applications')}
            - Tỷ lệ tôi đã phản hồi (mời/từ chối): {kpi_data.get('response_rate')}%
            - Số hồ sơ tôi đã mời phỏng vấn: {kpi_data.get('invited_count')}
            - Điểm AI trung bình của hồ sơ: {kpi_data.get('avg_ai_score')} / 100

            Phân bổ trạng thái hồ sơ (Phễu tuyển dụng):
            {funnel_str}

            Dựa trên các số liệu này, hãy đưa ra 3 NHẬN XÉT ngắn gọn và 1 GỢI Ý HÀNH ĐỘNG (call-to-action) để cải thiện quy trình.
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
    """
    Hàm chuyên dụng để tính điểm phù hợp giữa CV và JD.
    Sử dụng prompt theo chuỗi tư duy (Chain-of-Thought) để AI phân tích sâu hơn
    và trả về JSON để đảm bảo tính chính xác của điểm số.
    """
    response_content = "" 
    try:
        prompt = f"""
        Bạn là một chuyên gia tuyển dụng AI. Hãy phân tích CV và JD dưới đây theo 4 bước sau:
        1.  **Phân tích JD:** Rút ra 3-5 yêu cầu quan trọng nhất (kỹ năng, kinh nghiệm) từ JD.
        2.  **Đối chiếu CV:** Tìm bằng chứng cụ thể trong CV khớp với từng yêu cầu của JD.
        3.  **Đánh giá:** Ghi nhận những điểm mạnh (khớp) và điểm yếu (không khớp/thiếu).
        4.  **Cho điểm:** Dựa trên phân tích ở bước 3, hãy cho một điểm số duy nhất từ 0 đến 100.

        Hãy trả về kết quả dưới dạng MỘT CHUỖI JSON HỢP LỆ và KHÔNG có gì khác.
        JSON object phải có dạng: {{"score": <số_nguyên>}}

        --- JD (Job Description) ---
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

    context = {
        'profile': profile
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

        candidate_profile, _ = Profile.objects.get_or_create(user=application.candidate)
        candidate_name = candidate_profile.full_name or application.candidate.username
        job_title = application.job.title
        recruiter_profile, _ = Profile.objects.get_or_create(user=request.user)
        recruiter_name = recruiter_profile.full_name or request.user.username

        try:
            client = groq.Groq(api_key=settings.GROQ_API_KEY)
            ai_generated_email = ""
            new_status = ""
            success_message = ""
            
            if decision == 'invite':
                interview_time_str = request.POST.get('interview_time')
                interview_date_str = request.POST.get('interview_date')
                interview_location = request.POST.get('interview_location')
                
                try:
                    interview_date_obj = datetime.date.fromisoformat(interview_date_str)
                    formatted_date = interview_date_obj.strftime('%d/%m/%Y')
                    combined_interview_time_for_ai = f"{interview_time_str} ngày {formatted_date}"
                except (ValueError, TypeError):
                    combined_interview_time_for_ai = f"{interview_time_str} {interview_date_str}"

                prompt = f"""
                Viết một email mời phỏng vấn chuyên nghiệp cho ứng viên.
                - Tên ứng viên: {candidate_name}
                - Vị trí: {job_title}
                - Thời gian: {combined_interview_time_for_ai}
                - Địa điểm/Link: {interview_location}
                - Ghi chú thêm: {custom_message}
                - Người gửi: {recruiter_name}
                Yêu cầu ứng viên xác nhận. KHÔNG VIẾT TIÊU ĐỀ EMAIL.
                """
                new_status = 'invited'
                success_message = f"Đã gửi lời mời phỏng vấn đến {candidate_name}."

            elif decision == 'reject_cv':
                prompt = f"""
                Viết một email từ chối hồ sơ (vòng CV) chuyên nghiệp, lịch sự.
                - Tên ứng viên: {candidate_name}
                - Vị trí: {job_title}
                - Ghi chú thêm (lý do nếu có): {custom_message}
                - Người gửi: {recruiter_name}
                Cảm ơn họ đã ứng tuyển và chúc may mắn. KHÔNG VIẾT TIÊU ĐỀ EMAIL.
                """
                new_status = 'rejected'
                success_message = f"Đã gửi thông báo từ chối (lọc CV) đến {candidate_name}."

            elif decision == 'pass':
                prompt = f"""
                Viết một email CHÚC MỪNG TRÚNG TUYỂN chuyên nghiệp.
                - Tên ứng viên: {candidate_name}
                - Vị trí: {job_title}
                - Ghi chú thêm (về lương, ngày bắt đầu...): {custom_message}
                - Người gửi: {recruiter_name}
                Chào mừng họ đến với công ty. KHÔNG VIẾT TIÊU ĐỀ EMAIL.
                """
                new_status = 'passed'
                success_message = f"Đã gửi thông báo trúng tuyển đến {candidate_name}."

            elif decision == 'reject_interview':
                prompt = f"""
                Viết một email từ chối hồ sơ (vòng Phỏng vấn) chuyên nghiệp, lịch sự.
                - Tên ứng viên: {candidate_name}
                - Vị trí: {job_title}
                - Ghi chú thêm: {custom_message}
                - Người gửi: {recruiter_name}
                Cảm ơn họ đã tham gia phỏng vấn và chúc may mắn. KHÔNG VIẾT TIÊU ĐỀ EMAIL.
                """
                new_status = 'rejected'
                success_message = f"Đã gửi thông báo từ chối (rớt PV) đến {candidate_name}."

            else:
                messages.error(request, 'Lựa chọn không hợp lệ.')
                return redirect('process_application', application_id=application.id)
            
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.1-8b-instant", 
            )
            ai_generated_email = chat_completion.choices[0].message.content
            
            action_url = None
            if decision == 'invite':
                action_url = request.build_absolute_uri(
                    reverse('confirm_interview', kwargs={'application_id': application.id})
                )
            
            Notification.objects.create(
                recipient=application.candidate,
                message=ai_generated_email,
                action_url=action_url 
            )
            
            application.status = new_status
            application.save()
            messages.success(request, success_message)

        except Exception as e:
            print(f"Lỗi Groq API khi xử lý hồ sơ: {e}")
            messages.error(request, 'Đã có lỗi xảy ra với AI. Không thể gửi thông báo.')

        return redirect('applicant_list', job_id=application.job.id)

    else:
        context = {
            'application': application,
            'current_status': application.status 
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
    """
    Hiển thị trang kết quả sau khi ứng viên nộp hồ sơ,
    bao gồm cả phân tích AI.
    """
    application = get_object_or_404(Application, pk=application_id, candidate=request.user)
    
    # Lấy kết quả phân tích từ session
    analysis_result = request.session.get('analysis_result', None)
    
    # Xóa session sau khi lấy
    if 'analysis_result' in request.session:
        del request.session['analysis_result']

    context = {
        'application': application,
        'analysis': analysis_result # Gửi kết quả (score, strengths, suggestions)
    }
    return render(request, 'recruitment/application_result.html', context)