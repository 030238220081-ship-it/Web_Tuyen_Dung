import base64
import time
import pyautogui
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import os

# --- PHẦN CẤU HÌNH ---
# 1. Thay thế bằng thông tin Google Cloud Project của bạn
PROJECT_ID = "gen-lang-client-0611229210"
LOCATION = "asia-southeast1"

# 2. Thông tin đăng nhập và đường dẫn file
WEBSITE_URL = "https://web-tuyen-dung-moyp.onrender.com"
USERNAME = "Ungvien"
PASSWORD = "Hungnq142@"
CV_PATH = r"C:\\Users\\hung\Downloads\\Nguyễn_Quốc_Hưng_CV_Intern_BA.pdf"

try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-1.5-pro-preview-0409")
    print("✅ Kết nối thành công đến Vertex AI.")
except Exception as e:
    print(f"❌ Lỗi khi khởi tạo Vertex AI: {e}")
    print("Vui lòng kiểm tra lại PROJECT_ID và thiết lập xác thực Google Cloud.")
    exit()

def capture_and_prompt(task_description: str) -> str:
    """Chụp ảnh màn hình, gửi đến Gemini và nhận lại lệnh hành động."""
    print(f"🧠 Đang suy nghĩ: {task_description}")
    
    screenshot_path = "temp_screen.png"
    pyautogui.screenshot(screenshot_path)

    with open(screenshot_path, "rb") as image_file:
        image_data = base64.b64encode(image_file.read()).decode('utf-8')
    
    image_part = Part.from_data(
        mime_type="image/png",
        data=base64.b64decode(image_data)
    )

    prompt = [
        "Bạn là một AI điều khiển máy tính. Nhiệm vụ của bạn là thực hiện yêu cầu sau:",
        f"'{task_description}'",
        "Dựa vào ảnh màn hình, hãy trả về MỘT lệnh duy nhất để thực hiện bước tiếp theo.",
        "Các định dạng lệnh hợp lệ:",
        "  - CLICK X Y (ví dụ: CLICK 850 420)",
        "  - TYPE [nội dung cần gõ]",
        "  - PASTE [nội dung cần dán]",
        "  - KEYDOWN [tên phím] (ví dụ: KEYDOWN enter)",
        "  - SCREENSHOT [tên file] (ví dụ: SCREENSHOT ket_qua.png)",
        "  - WAIT [số giây] (ví dụ: WAIT 5)",
        image_part
    ]
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"❌ Lỗi khi gọi API của Gemini: {e}")
        return "WAIT 5" # Nếu lỗi, thử chờ và thử lại ở bước sau

def execute_action(action_command: str):
    """Thực thi lệnh hành động do Gemini trả về."""
    print(f"⚡ Thực hiện lệnh: {action_command}")
    parts = action_command.strip().split()
    command = parts[0].upper()
    
    try:
        if command == "CLICK":
            x, y = int(parts[1]), int(parts[2])
            pyautogui.click(x, y)
        elif command == "TYPE":
            text_to_type = " ".join(parts[1:])
            pyautogui.typewrite(text_to_type, interval=0.05)
        elif command == "PASTE":
            text_to_paste = " ".join(parts[1:])
            pyautogui.hotkey('ctrl', 'v', interval=0.1) # Dùng paste thay vì gõ cho đường dẫn
        elif command == "KEYDOWN":
            pyautogui.press(parts[1].lower())
        elif command == "SCREENSHOT":
            filename = parts[1]
            pyautogui.screenshot(filename)
            print(f"📸 Đã chụp màn hình và lưu với tên '{filename}'")
        elif command == "WAIT":
            seconds = int(parts[1])
            print(f"⏳ Chờ trong {seconds} giây...")
            time.sleep(seconds)
        else:
            print(f"⚠️ Lệnh không xác định: {action_command}")
    except Exception as e:
        print(f"❌ Lỗi khi thực thi lệnh '{action_command}': {e}")
    
    time.sleep(2.5) # Chờ 2.5 giây sau mỗi hành động để giao diện cập nhật

# --- KỊCH BẢN CHÍNH ---

def run_automation_flow():
    """Tuần tự thực hiện các bước trong quy trình tự động hóa."""

    # Bước 1 & 2: Mở trình duyệt và truy cập trang web
    print(f"🚀 Bắt đầu quy trình, đang mở trang web: {WEBSITE_URL}")
    pyautogui.press('win')
    time.sleep(1)
    pyautogui.typewrite('chrome')
    pyautogui.press('enter')
    time.sleep(3)
    pyautogui.typewrite(WEBSITE_URL)
    pyautogui.press('enter')
    time.sleep(5)

    # Danh sách các nhiệm vụ cần thực hiện
    tasks = [
        "Nhấp vào nút 'Đăng nhập' màu xanh nước biển ở góc trên cùng bên phải.",
        f"Tìm ô 'Tên đăng nhập' và gõ vào đó '{USERNAME}'.",
        f"Tìm ô 'Mật khẩu' và gõ vào đó '{PASSWORD}'.",
        "Nhấp vào nút 'Đăng nhập' để vào trang web.",
        "WAIT 3", # Chờ trang đăng nhập thành công
        "Nhấp vào ảnh đại diện (avatar) của người dùng ở góc trên bên phải.",
        "Trong menu vừa xuất hiện, nhấp vào mục 'Quản lý hồ sơ của tôi'.",
        "Tìm và nhấp vào nút hoặc khu vực có chữ 'Thay đổi CV' hoặc biểu tượng tải lên.",
        # Bước upload CV cần xử lý đặc biệt, không dùng Gemini
        f"PASTE_DIRECTLY {CV_PATH}", 
        "Nhấp vào nút 'Lưu thay đổi'.",
        "WAIT 3",
        "Tìm và nhấp vào mục 'AI Tìm việc phù hợp' trên thanh điều hướng.",
        "WAIT 10", # Chờ AI đề xuất
        "Tìm vị trí công việc có chứa chữ 'Business Analyst' và nhấp vào nút 'Ứng tuyển nhanh' màu xanh dương tương ứng.",
        "Tìm và nhấp vào nút hoặc tab có tên 'AI nhận xét CV'.",
        "Nhấp vào thanh xổ xuống để chọn vị trí công việc.",
        "Trong danh sách vừa xổ xuống, tìm và nhấp vào mục 'Thực tập sinh Business Analyst'.",
        "Nhấp vào nút có chữ 'Phân tích & nhận xét CV'.",
        "WAIT 7", # Chờ kết quả phân tích
        "SCREENSHOT ket_qua_nhan_xet_cv.png"
    ]

    for task in tasks:
        # Xử lý các trường hợp đặc biệt không cần AI
        if task.startswith("PASTE_DIRECTLY"):
            path = task.split(" ", 1)[1]
            print(f"⚡ Thực hiện lệnh: Dán trực tiếp đường dẫn {path}")
            time.sleep(2) # Chờ cửa sổ file mở ra
            pyautogui.write(path) # Dùng write để xử lý tiếng Việt
            time.sleep(1)
            pyautogui.press('enter')
            time.sleep(2.5)
            continue
        elif task.startswith("WAIT"):
            execute_action(task)
            continue
            
        # Quy trình chuẩn: Nhìn -> Suy nghĩ -> Hành động
        action_to_take = capture_and_prompt(task)
        execute_action(action_to_take)
    
    print("🎉 Quy trình tự động hóa đã hoàn tất!")

if __name__ == "__main__":
    # Đếm ngược 5 giây trước khi bắt đầu, cho bạn thời gian chuẩn bị
    print("Chuẩn bị bắt đầu sau 5 giây. Vui lòng không sử dụng chuột và bàn phím.")
    for i in range(5, 0, -1):
        print(f"{i}...")
        time.sleep(1)
    
    run_automation_flow()