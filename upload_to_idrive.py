import boto3
import os

# Credentials from dashboard
ACCESS_KEY = 'Nx4BNh28ia1Xehrsi6vw'
SECRET_KEY = 'ppvp5a5yP0rjHJnAHIflbREs3kOY2hgqD5t4NUyv'
ENDPOINT = 'https://s3.us-west-2.idrivee2.com'
BUCKET_NAME = 'ashm-abo-nwaf-site'
FILE_PATH = r'c:\Users\IT\Documents\GitHub\ashm-abo-nwaf\site_backup.zip'
OBJECT_NAME = 'site_backup.zip'

def upload_file():
    session = boto3.session.Session()
    s3_client = session.client(
        service_name='s3',
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        endpoint_url=ENDPOINT,
    )
    
    try:
        print(f"Uploading {FILE_PATH} to bucket {BUCKET_NAME}...")
        s3_client.upload_file(FILE_PATH, BUCKET_NAME, OBJECT_NAME)
        print("Upload Successful!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    upload_file()
