from flask import Flask, request, render_template, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
from google.cloud import storage
import io
import os
import re

app = Flask(__name__)

# GCP Configuration
GCP_BUCKET_NAME = "my-data-bucket-qinvst"
RAW_FILE = "output.xlsx"
CLEANED_FILE = "cleaned_output.xlsx"
GCP_CREDENTIALS_PATH = r"C:\Users\pande\OneDrive\Documents\keys\prismatic-night-454303-s1-412af151235d.json"

# Function to process the HTML file
def process_html_file(html_url):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # Run without opening a browser
    driver = webdriver.Chrome(options=options)
    
    try:
        # Load the HTML file
        driver.get(html_url)
        table = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "table")))

        # Extract column headers
        headers = [header.text.strip() for header in table.find_elements(By.TAG_NAME, "th")]

        # Extract table rows
        rows = table.find_elements(By.TAG_NAME, "tr")
        data = []

        for row in rows:
            cols = [col.text.strip() for col in row.find_elements(By.TAG_NAME, "td")]
            if cols:
                data.append(cols)

        # Convert to DataFrame and save to Excel
        df = pd.DataFrame(data, columns=headers)
        df.to_excel(RAW_FILE, index=False)
        
        # Upload raw file to GCP
        upload_to_gcs(RAW_FILE, RAW_FILE)

        # Process and clean the file after uploading
        process_and_clean_data()

        return "File processed, cleaned, and uploaded successfully!"

    except Exception as e:
        return f"Error: {e}"

    finally:
        driver.quit()

# Function to upload a file to GCP
def upload_to_gcs(source_file, destination_blob):
    storage_client = storage.Client.from_service_account_json(GCP_CREDENTIALS_PATH)
    bucket = storage_client.bucket(GCP_BUCKET_NAME)
    blob = bucket.blob(destination_blob)
    blob.upload_from_filename(source_file)
    print(f"File uploaded to GCP: {destination_blob}")

# Function to clean and process data
def process_and_clean_data():
    # Initialize GCP Storage Client
    storage_client = storage.Client.from_service_account_json(GCP_CREDENTIALS_PATH)
    bucket = storage_client.bucket(GCP_BUCKET_NAME)
    blob = bucket.blob(RAW_FILE)

    # Download file from GCP as a Pandas DataFrame
    data = blob.download_as_bytes()
    df = pd.read_excel(io.BytesIO(data))

    print("Data fetched successfully!")

    # Ensure "Comments" column exists
    if "Comments" not in df.columns:
        df["Comments"] = None

    # Convert SEQ NUMBER column to string for processing
    df.iloc[:, 0] = df.iloc[:, 0].astype(str)

    # Create a new DataFrame to store cleaned data
    cleaned_data = []
    last_valid_row = None  # Keep track of the last valid data row

    # Iterate through each row
    for index, row in df.iterrows():
        seq_number = row.iloc[0]  # First column (SEQ NUMBER)

        if seq_number.isdigit():  # If it's a number, it's a valid row
            last_valid_row = row.copy()  # Store this row as the last valid row
            cleaned_data.append(last_valid_row)  # Add to cleaned dataset
        else:  # If it's a description
            if last_valid_row is not None:  # Ensure we have a valid row to attach this comment
                last_valid_row = last_valid_row.copy()  # Create a separate object
                last_valid_row["Comments"] = str(row.iloc[0])  # Store description in the Comments column
                cleaned_data[-1] = last_valid_row  # Update last stored row

    # Convert cleaned data back to a DataFrame
    df_cleaned = pd.DataFrame(cleaned_data)

    # Replace NaN values in Comments column
    df_cleaned["Comments"] = df_cleaned["Comments"].replace(["nan", pd.NA, None, float("nan")], "Not Assigned").fillna("Not Assigned")

    # Remove [numbers] from the Comments column
    df_cleaned["Comments"] = df_cleaned["Comments"].str.replace(r"\[\d+(\.\d+)?\]\s*", "", regex=True)

    # Reset index
    df_cleaned.reset_index(drop=True, inplace=True)

    print("Data cleaned successfully!")

    # Save cleaned DataFrame to a new Excel file
    df_cleaned.to_excel(CLEANED_FILE, index=False)

    # Upload cleaned file to GCP in the "Processed" folder
    upload_to_gcs(CLEANED_FILE, CLEANED_FILE)

    print(f"Cleaned data uploaded to GCP as {CLEANED_FILE}!")

# Flask route for the frontend
@app.route("/")
def index():
    return render_template("index.html")

# Flask route for processing the HTML file
@app.route("/process", methods=["POST"])
def process():
    data = request.json
    html_url = data.get("html_url")

    if not html_url:
        return jsonify({"error": "No URL provided"}), 400

    result = process_html_file(html_url)
    return jsonify({"message": result})

if __name__ == "__main__":
    app.run(debug=True)
