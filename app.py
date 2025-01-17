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

# Utility to check if file is PDF
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Schedule parsing function
def parse_schedule(schedule_text):
    """Parses multi-line schedule strings into structured day and time components."""
    days_times = []

    if not schedule_text.strip():
        return days_times  # Return empty for blank schedules

    schedule_lines = schedule_text.split('\n')

    pattern = r'([A-Z]+)\s(\d{1,2}:\d{2})\s?(AM|PM)-(\d{1,2}(:\d{2})?)\s?(AM|PM)?'

    for line in schedule_lines:
        line = line.strip()
        matches = re.findall(pattern, line)
        if matches:
            for match in matches:
                day, start, start_period, end, _, end_period = match
                if not end_period:
                    end_period = start_period
                days_times.append({
                    "day": day,
                    "time_start": start,
                    "time_start_daytime": start_period,
                    "time_end": end,
                    "time_end_daytime": end_period
                })

    return days_times

# Table extraction and parsing function
def extract_and_transform_table(file_path):
    # Extract tables using both lattice and stream methods
    tables_lattice = camelot.read_pdf(file_path, flavor='lattice', pages='all')
    tables_stream = camelot.read_pdf(file_path, flavor='stream', pages='all')

    # Combine both TableLists
    all_tables = []
    all_tables.extend(tables_lattice)
    all_tables.extend(tables_stream)

    if len(all_tables) == 0:
        return {"error": "No tables found"}

    table = all_tables[0].df
    headers = table.iloc[0].tolist()
    data_rows = table.iloc[1:]

    result = []

    for _, row in data_rows.iterrows():
        subject_code = row[1].strip()
        subject = row[2].replace('\n', ' ')
        section = row[3].strip()
        schedule = row[8].strip().replace('\n', ' ')
        room = row[9].replace('\n', ' ').strip()
        schedule_details = parse_schedule(schedule)
        days = " ".join(sorted(set(item['day'] for item in schedule_details)))

        course = {
            "subject_code": subject_code,
            "subject": subject,
            "section": section,
            "room": room,
            "days": days,
            "schedule": schedule_details
        }
        result.append(course)

    return result

# Flask route to handle PDF upload
@app.route('/upload', methods=['POST'])
def upload_pdf():
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

    # Extract data from PDF
    try:
        result = extract_and_transform_table(file_path)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # Clean up uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)

# Run Flask App
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
