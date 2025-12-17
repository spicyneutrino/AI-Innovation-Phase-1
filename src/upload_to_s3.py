import boto3
from pathlib import Path
from botocore.exceptions import ClientError

BUCKET_NAME = "ms-sos-regulations-data-december-2025" 
LOCAL_DATA_FOLDER = Path("data") 

def upload_folder_to_s3():
    s3 = boto3.client('s3')

    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
        print(f"Bucket '{BUCKET_NAME}' already exists.")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"Creating new bucket: {BUCKET_NAME}...")
            s3.create_bucket(Bucket=BUCKET_NAME)
        elif error_code == '403':
            print(f"Error: Access Denied. Permission check needed.")
            return
        else:
            print(f"Error checking bucket: {e}")
            return

    if not LOCAL_DATA_FOLDER.exists():
        print(f"Error: Folder '{LOCAL_DATA_FOLDER}' not found.")
        print("   -> Please create a folder named 'data' and put your PDFs inside it.")
        return

    print(f"Starting upload from '{LOCAL_DATA_FOLDER}'...")
    file_count = 0
    
    for file_path in LOCAL_DATA_FOLDER.rglob('*'):
        if file_path.is_file():
            # Create S3 Key (Relative Path in Bucket)
            s3_key = file_path.relative_to(LOCAL_DATA_FOLDER).as_posix()

            try:
                print(f"   Uploading: {file_path.name}...")
                s3.upload_file(str(file_path), BUCKET_NAME, s3_key)
                file_count += 1
            except Exception as e:
                print(f"   Failed to upload {file_path.name}: {e}")

    print(f"\n Success! Uploaded {file_count} files to s3://{BUCKET_NAME}")

if __name__ == "__main__":
    upload_folder_to_s3()