import os
import fitz  
import docx

def extract_text_from_cv(cv_file):
    """
    Trích xuất văn bản từ file CV (hỗ trợ cả PDF và DOCX).
    cv_file là một đối tượng FieldFile của Django.
    """
    try:
        file_name, file_extension = os.path.splitext(cv_file.name)
        file_extension = file_extension.lower()

        text = ""
        
        with cv_file.open('rb') as f:
            if file_extension == '.pdf':
                doc = fitz.open(stream=f, filetype='pdf')
                for page in doc:
                    text += page.get_text()
                doc.close()
                
            elif file_extension == '.docx':
                doc = docx.Document(f)
                for para in doc.paragraphs:
                    text += para.text + '\n'
            
            else:
                print(f"Định dạng file không được hỗ trợ: {file_extension}")
                return None

        return text

    except Exception as e:
        print(f"Lỗi nghiêm trọng khi đọc file CV '{cv_file.name}': {e}")
        return None