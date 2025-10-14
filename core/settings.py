from pathlib import Path
import os
import dj_database_url 
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('SECRET_KEY')
DEBUG = os.getenv('DEBUG', 'False') == 'True'


# === SỬA LỖI 1: XÓA 'https://' KHỎI ALLOWED_HOSTS ===
ALLOWED_HOSTS = ['web-tuyen-dung-moyp.onrender.com', 'localhost', '127.0.0.1']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'cloudinary_storage', 
    'django.contrib.staticfiles',
    'cloudinary',
    'recruitment',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        # This line tells Django to look for templates inside app directories
        # (like the admin app's templates).
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Your custom context processor
                'recruitment.context_processors.notifications_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'


# === SỬA LỖI 2: CẤU HÌNH DATABASE CHO RENDER ===
# Xóa hoặc comment out cấu hình sqlite3 cũ
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

# Thêm cấu hình mới, tự động đọc từ DATABASE_URL
DATABASES = {
    'default': dj_database_url.config(
        # Mặc định sẽ đọc từ biến môi trường DATABASE_URL
        conn_max_age=600,
        ssl_require=True # Bắt buộc SSL cho kết nối an toàn trên Render
    )
}


# --- Password validation (Giữ nguyên) ---
AUTH_PASSWORD_VALIDATORS = [
    # ... (Giữ nguyên phần này) ...
]

# --- Internationalization (Giữ nguyên) ---
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True


# --- Static and Media files (Đã đúng) ---
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# --- Cấu hình khác (Đã đúng) ---
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'recruitment.CustomUser'
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# === Đề xuất cải thiện (Tùy chọn) ===
LOGIN_REDIRECT_URL = 'job_list' # Chuyển hướng về trang chủ sau khi đăng nhập thành công
LOGOUT_REDIRECT_URL = 'job_list' # Chuyển hướng về trang chủ sau khi đăng xuất
LOGIN_URL = 'login' # URL của trang đăng nhập

# Cấu hình Cloudinary
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.getenv('CLOUDINARY_API_KEY'),
    'API_SECRET': os.getenv('CLOUDINARY_API_SECRET'),
}

# DÒNG QUAN TRỌNG NHẤT: CHỈ ĐỊNH CLOUDINARY LÀ NƠI LƯU TRỮ MẶC ĐỊNH
DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
