import fitz
from PIL import Image
from pdf2image import convert_from_path
import pytesseract
from flask import Flask, request, jsonify
import camelot
import re
import os
from werkzeug.utils import secure_filename

# Initialize Flask App
app = Flask(__name__)

# Set upload folder and allowed file types
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(pdf_path):
    """Extracts text from a PDF using OCR with improved settings."""
    images = convert_from_path(pdf_path, dpi=300)  # High resolution
    text = "\n".join([pytesseract.image_to_string(
        img, config="--psm 6 --oem 3", lang="eng") for img in images])
    return text


def extract_teacher_details(text):
    """Extracts faculty details like name, rank, designation, and email from OCR text."""
    teacher_details = {}

    # Normalize text
    cleaned_text = re.sub(r'\n+', ' ', text)  # Remove excessive newlines
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()  # Normalize spaces
    cleaned_text = re.sub(r' :', ':', cleaned_text)  # Handle OCR formatting issues

    # Print cleaned text for debugging (Optional)
    # print(cleaned_text)

    # Updated regex patterns
    patterns = {
        "faculty_name": r"Faculty Name\s*:?\s*([\w\s\.\-]+?)(?=\s+Designation)",
        "rank": r"Rank\s*:?\s*([\w\s\d]+)(?=\s+Status|Major Discipline)",
        "major_discipline": r"Major Discipline\s*:?\s*([\w\s]+)(?=\s+Email Address|$)",
        "designation": r"Designation\s*:?\s*([\w\s\d]+)(?=\s+Rank|Status)",
        "status": r"Status\s*:?\s*([\w\s-]+)(?=\s+Email Address|Major Discipline|$)",
        # Improved email regex: allows extra spaces, captures full email correctly
        "email_address": r"Email Address\s*:?\s*(?:\S*\s+)*([\w.-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        "campus_college": r"COLLEGE OF\s*([\w\s]+?)\s*FACULTY LOAD"
    }

    # Extract using regex
    for key, pattern in patterns.items():
        match = re.search(pattern, cleaned_text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if key == "email_address":
                value = value.replace(" ", "")  # Remove any extra spaces in emails
            teacher_details[key] = value
        else:
            teacher_details[key] = "Not Found"

    return teacher_details


def extract_faculty_credit_and_load(text):
    """Extracts faculty credit and designation load released from OCR text."""
    faculty_load_details = {}

    cleaned_text = re.sub(r'\n+', ' ', text).replace(':', '')

    patterns = {
        "faculty_credit": r"FACULTY CREDIT [-\s]+(\d+(\.\d+)?)",
        "designation_load_released": r"DESIGNATION, LOAD RELEASED [-\s]+(\d+(\.\d+)?)"
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, cleaned_text, re.IGNORECASE)
        faculty_load_details[key] = match.group(1).strip() if match else "Not Found"

    return faculty_load_details


def extract_and_transform_table(pdf_path):
    """Extracts structured data from a table in the PDF."""
    try:
        tables = camelot.read_pdf(pdf_path, flavor='stream', pages='all')

        if len(tables) == 0:
            return {"error": "No tables found in the PDF."}

        table = tables[0].df  # Assume first table contains needed data
        headers = table.iloc[0].tolist()
        data_rows = table.iloc[1:]

        result = []
        for _, row in data_rows.iterrows():
            if row[1].strip() and row[2].strip():
                course = {
                    "schedule_id": row[1].strip(),
                    "subject_code": row[2].strip(),
                    "subject": row[3].replace('\n', ' '),
                    "subject_credit": row[4].strip(),
                    "faculty_credit": row[5].strip(),
                    "college_code": row[6].strip(),
                    "hr_per_week": row[7].strip(),
                    "hr_per_sem": row[8].strip(),
                    "section": row[9].strip(),
                    "room": row[12].replace('\n', ' ').strip(),
                    "total_students": row[13].strip()
                }
                result.append(course)

        extracted_text = extract_text_from_pdf(pdf_path)
        details = extract_teacher_details(extracted_text)
        credit_and_load = extract_faculty_credit_and_load(extracted_text)

        data = {
            "schedule": result,
            "details": details,
            "credit_and_load": credit_and_load
        }

        return data

    except Exception as e:
        app.logger.error(f"Error extracting table: {str(e)}")
        return {"error": f"Failed to process table: {str(e)}"}


@app.route('/upload', methods=['POST'])
def upload_pdf():
    """Flask route to handle PDF upload and extraction."""
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF files are allowed"}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        result = extract_and_transform_table(file_path)
        return jsonify(result), 200
    except Exception as e:
        app.logger.error(f"Unexpected error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        # Clean up uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)


# Run Flask App
if __name__ == "__main__":
    app.run(debug=True)
