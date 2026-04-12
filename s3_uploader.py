import boto3
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Explicitly setting the bucket name to avoid .env issues
BUCKET_NAME = "msu-ai-hub-sos-phase-2"
# Get the absolute path to make sure we aren't looking in the wrong place
LOCAL_DATA_FOLDER = Path.cwd() / "var/sos_crawler/downloads"

def upload_folder_to_s3():
    s3 = boto3.client('s3')

    print(f"Current working directory: {Path.cwd()}")
    print(f"Looking for data in: {LOCAL_DATA_FOLDER}")

    if not LOCAL_DATA_FOLDER.exists():
        print(f"FAILED: Folder '{LOCAL_DATA_FOLDER}' does not exist!")
        return

    print(f"Starting upload to bucket: {BUCKET_NAME}")
    file_count = 0
    
    for file_path in LOCAL_DATA_FOLDER.rglob('*'):
        if file_path.is_file():
            # This preserves the AL/, TX/ folder structure in S3
            s3_key = file_path.relative_to(LOCAL_DATA_FOLDER).as_posix()
            try:
                print(f"   Uploading: {s3_key}...")
                s3.upload_file(str(file_path), BUCKET_NAME, s3_key)
                file_count += 1
            except Exception as e:
                print(f"   Failed {s3_key}: {e}")

    print(f"\nSUCCESS! Uploaded {file_count} files to s3://{BUCKET_NAME}")

if __name__ == "__main__":
    upload_folder_to_s3()