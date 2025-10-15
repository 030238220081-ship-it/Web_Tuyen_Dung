from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser
from .models import Profile

class CustomUserCreationForm(forms.ModelForm):
    # Phần định nghĩa password và password2 giữ nguyên, đảm bảo chúng có widget
    password = forms.CharField(
        label='Mật khẩu', 
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    password2 = forms.CharField(
        label='Xác nhận mật khẩu', 
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = CustomUser
        # === THAY ĐỔI QUAN TRỌNG NHẤT: XÓA 'user_type' KHỎI ĐÂY ===
        fields = ('username', 'email') 
        help_texts = {
            'username': None,
        }
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean_password2(self):
        cd = self.cleaned_data
        if cd['password'] != cd['password2']:
            raise forms.ValidationError('Mật khẩu không khớp.')
        return cd['password2']

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['full_name', 'summary', 'cv_file']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'summary': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'cv_file': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'full_name': 'Họ và tên',
            'summary': 'Tóm tắt bản thân / Giới thiệu kỹ năng',
            'cv_file': 'Tải lên CV (PDF, DOCX)',
        }




