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


def split_after_first_am_pm(schedule_text):
    """
    Splits a schedule string into two parts after detecting the first 'AM' or 'PM'.
    Returns an array of the split parts.
    """
    array = []  # Initialize an empty list
    match = re.search(r'(AM|PM)\s', schedule_text)
    if match:
        split_index = match.end()
        first_part = schedule_text[:split_index].strip()
        second_part = schedule_text[split_index:].strip()
        array.extend([first_part, second_part])  # Add both parts to the array
    else:
        # Add the whole string to the array
        array.append(schedule_text.strip())
    return array


def parse_schedule(schedule_text):
    """
    Parses schedule strings into structured components.
    Handles cases with one schedule or multiple schedules separated by spaces.
    """
    days_times = []

    # Split the schedule on two or more spaces
    schedule_parts = split_after_first_am_pm(schedule_text)
    print("Split schedule into parts:", schedule_parts)  # Debugging output

    # Regex pattern to match day and time (e.g., "F 7:30 AM-10:00 AM")
    pattern = r'([A-Z]+)\s+(\d{1,2}:\d{2})\s?(AM|PM)?\s*-\s*(\d{1,2}:\d{2})\s?(AM|PM)?'

    for part in schedule_parts:
        if not part.strip():  # Skip empty parts
            continue

        # Match the regex on the current part
        matches = re.findall(pattern, part.strip())
        for day, start, start_period, end, end_period in matches:
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
    app.run()
