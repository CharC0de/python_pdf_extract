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


def preprocess_schedule_text(schedule_text):
    """
    Preprocess schedule_text to correct minor formatting errors and normalize to
    the format: "{day/s} {time-start}-{time-end}".
    """
    # Normalize spaces
    schedule_text = re.sub(r'\s+', ' ', schedule_text.strip())

    # Ensure space before and after AM/PM
    schedule_text = re.sub(r'([APap][Mm])(\d)', r'\1 \2', schedule_text)
    schedule_text = re.sub(r'(\d)([APap][Mm])', r'\1 \2', schedule_text)

    # Ensure dash between times if missing
    schedule_text = re.sub(
        r'(\d{1,2}:\d{2}\s*[APap][Mm])\s*(\d{1,2}:\d{2}\s*[APap][Mm])', r'\1-\2', schedule_text)

    # Ensure space around dash
    schedule_text = re.sub(r'(\d)-(\d)', r'\1 - \2', schedule_text)

    # Match and format the day and time range (with space in time)
    pattern = r"([A-Z]+)\s*(\d{1,2}:\d{2}\s*[APap][Mm]\s*-\s*\d{1,2}:\d{2}\s*[APap][Mm])"
    match = re.match(pattern, schedule_text)
    if match:
        days, times = match.groups()
        # Add space before AM/PM in times, only if not already present
        times = re.sub(r'(?<!\s)([APap][Mm])', r' \1', times)
        return f"{days} {times.strip()}"  # Remove leading/trailing spaces
    return schedule_text


def split_same_time_diff_day(schedule_text: str) -> list:
    """
    Splits a schedule string into separate schedules if multiple days are present with the same time.
    For example:
        "TTH 9:30 AM-12:00 PM" -> ["T 9:30 AM-12:00 PM", "TH 9:30 AM-12:00 PM"]
    """
    # Preprocess to normalize spacing
    # Normalize extra spaces
    schedule_text = re.sub(r'\s+', ' ', schedule_text.strip())

    # Updated regex to allow flexible spacing
    pattern = r"([A-Z]+)\s+(\d{1,2}:\d{2}\s*[APap][Mm]\s*-\s*\d{1,2}:\d{2}\s*[APap][Mm])"

    match = re.match(pattern, schedule_text)
    if not match:
        return [schedule_text.strip()]  # If no match, return input as is

    # Split match groups
    days, times = match.groups()

    # Break days into individual days (e.g., TTH -> T, TH)
    day_mapping = {
        "M": "M", "T": "T", "W": "W", "R": "TH", "F": "F",
        "S": "S", "U": "SU"  # Add any additional mappings as needed
    }
    individual_days = []
    i = 0
    while i < len(days):
        # Handle "TH" (two-character day)
        if days[i] == "T" and i + 1 < len(days) and days[i + 1] == "H":
            individual_days.append(day_mapping["R"])  # Map "TH"
            i += 2  # Skip "H"
        else:
            individual_days.append(day_mapping.get(days[i], days[i]))
            i += 1

    # Combine each day with the time range
    schedules = [f"{day} {times}" for day in individual_days]
    return schedules


def split_two_schedules(schedule: str) -> list:
    """Splits two schedules based on the pattern where the first ends with 'M' and the second starts after spaces."""
    pattern = r'(.*M)\s+([A-Z].*)'
    match = re.search(pattern, schedule)
    if match:
        return [match.group(1), match.group(2)]
    return [schedule]


def parse_schedule(schedule_text):
    """
    Parses schedule strings into structured components.
    Handles cases with one schedule or multiple schedules separated by spaces.
    """
    days_times = []

    # Split the schedule on two or more spaces
    print(schedule_text)
    schedule_parts = split_two_schedules(schedule_text)
    print("Split schedule into parts:", schedule_parts)  # Debugging output

    # Regex pattern to match day and time (e.g., "F 7:30 AM-10:00 AM")
    pattern = r'([A-Z]+)\s+(\d{1,2}:\d{2})\s?(AM|PM)?\s*-\s*(\d{1,2}:\d{2})\s?(AM|PM)?'

    for index, part in enumerate(schedule_parts):
        schedule_parts[index] = preprocess_schedule_text(part)
        print(preprocess_schedule_text(part))
    if len(schedule_parts) == 1:
        print(schedule_parts)
        schedule_parts = split_same_time_diff_day(schedule_parts[0])
        print(schedule_parts)

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
        lecUnits = row[4].strip()
        labUnits = row[5].strip()
        lecHours = row[6].strip()
        labHours = row[7].strip()
        schedule = row[8].strip().replace('\n', ' ')
        room = row[9].replace('\n', ' ').strip()
        noOfStudents = row[10].strip()
        schedule_details = parse_schedule(schedule)
        days = " ".join(sorted(set(item['day'] for item in schedule_details)))

        course = {
            "subject_code": subject_code,
            "subject": subject,
            "section": section,
            "room": room,
            "days": days,
            "lec_units": lecUnits,
            "lab_units": labUnits,
            "lec_hours": lecHours,
            "lab_hours": labHours,
            "schedule": schedule_details,
            "no_of_students": noOfStudents,
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
