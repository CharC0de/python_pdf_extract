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
    pattern = r"([A-Z]+)\s*(\d{1,2}:\d{2}\s*[APap][Mm]\s* - \s*\d{1,2}:\d{2}\s*[APap][Mm])"
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
    Allows handling of 'TH' and 'Th'.
    """
    schedule_text = re.sub(
        r'\s+', ' ', schedule_text.strip())  # Normalize spaces
    pattern = r"(?i)([A-Z]+)\s+(\d{1,2}:\d{2}\s*[APap][Mm]\s* - \s*\d{1,2}:\d{2}\s*[APap][Mm])"

    match = re.match(pattern, schedule_text)
    if not match:
        return [schedule_text.strip()]

    days, times = match.groups()
    days = days.upper()  # Normalize case

    day_mapping = {
        "M": "M", "T": "T", "W": "W", "R": "Th", "F": "F",
        "S": "S", "U": "SU"
    }

    individual_days = []
    i = 0
    while i < len(days):
        # Handle TH/Th
        if days[i] == "T" and i + 1 < len(days) and days[i + 1] in "Hh":
            individual_days.append(day_mapping["R"])
            i += 2
        else:
            individual_days.append(day_mapping.get(
                days[i].upper(), days[i].upper()))
            i += 1

    return [f"{day} {times}" for day in individual_days]


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
    pattern = r'(?i)([A-Z]+)\s+(\d{1,2}:\d{2})\s?(AM|PM)?\s* - \s*(\d{1,2}:\d{2})\s?(AM|PM)?'

    for index, part in enumerate(schedule_parts):
        schedule_parts[index] = preprocess_schedule_text(part)
        print("Preprocessed Part:", preprocess_schedule_text(part))
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


def extract_and_transform_table(pdf_path):
    # Extract tables using both lattice and stream methods
    tables_lattice = camelot.read_pdf(pdf_path, flavor='lattice', pages='all')
    tables_stream = camelot.read_pdf(pdf_path, flavor='stream', pages='all')

    # Combine both TableLists
    all_tables = []
    all_tables.extend(tables_lattice)
    all_tables.extend(tables_stream)

    if len(all_tables) == 0:
        print("No tables found.")
        return

    print(f"Total Tables Detected: {len(all_tables)}")

    # Use the first detected table (Table 1)
    table = all_tables[0].df

    # Extract header and rows
    headers = table.iloc[0].tolist()
    data_rows = table.iloc[1:]

    result = []
    total_subject_credit = ''
    total_faculty_credit = ''
    all_total_students = ''
    for _, row in data_rows.iterrows():
        if row[1] != "" and row[2].strip() != "" and row[3].strip() != "":
            print(f"Row columns: {len(row)} | Data: {row.tolist()}")

            # Map row data to the required JSON fields
            schedule_id = row[1].strip()
            schedule_id = re.sub(r'^\d+\.\s*', '', schedule_id)

            # Use regex to split on one or more successive newlines (\n+)
            schedule_parts_1 = re.split(
                r'\n+', row[10].strip()) if row[10].strip() else []
            schedule_parts_2 = re.split(
                r'\n+', row[11].strip()) if row[11].strip() else []

            # Ensure both lists have the same length by padding with empty strings
            max_len = max(len(schedule_parts_1), len(schedule_parts_2))
            schedule_parts_1 += [""] * (max_len - len(schedule_parts_1))
            schedule_parts_2 += [""] * (max_len - len(schedule_parts_2))

            # Pair corresponding elements together (aligning days with times)
            combined_schedule_parts = [
                f"{schedule_parts_1[i]} {schedule_parts_2[i]}".strip() for i in range(max_len)
            ]

            # Construct full schedule string
            full_schedule = " ".join(combined_schedule_parts).strip()

            # Parse only if there's a valid schedule

            schedule = parse_schedule(full_schedule) if full_schedule else []
            days = " ".join(sorted(set(item['day'] for item in schedule)))
            course = {
                "schedule_id": schedule_id,
                "subject_code": row[2].strip(),
                "subject": row[3].replace('\n', ' '),
                "subject_credit": row[4].strip(),
                "faculty_credit": row[5].strip(),
                "college_code": row[6].strip(),
                "hr_per_week": row[7].strip(),
                "hr_per_sem": row[8].strip(),
                "section": row[9].strip(),
                "schedule": schedule,
                "days": days,
                # Assuming 'Room' is in column 10
                "room": row[12].replace('\n', ' ').strip(),
                # Assuming 'Total Students' is in column 11
                "total_students": row[13].strip()
            }
            result.append(course)
        else:
            total_subject_credit = row[4].strip()
            total_faculty_credit = row[5].strip()
            all_total_students = row[13].strip()

    data = {
        "total_subject_credit": total_subject_credit,
        "total_faculty_credit": total_faculty_credit,
        "all_total_students": all_total_students,
        "schedule": result,
    }

    return data

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
