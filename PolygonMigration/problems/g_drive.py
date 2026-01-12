import os
import io
import logging
import concurrent.futures  # Added for parallel processing
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from googleapiclient.errors import HttpError
from django.conf import settings
from google.oauth2.credentials import Credentials
import google.auth.transport.requests

logger = logging.getLogger(__name__)

class GDriveManager:
    """
    A manager class to handle read/write operations for Google Drive.
    All operations are confined to the fixed ROOT_FOLDER_ID.
    """
    
    # Scope required to read/write files
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    # The fixed folder ID where all problem folders will be created
    ROOT_FOLDER_ID = settings.GDRIVE_ROOT_FOLDER_ID
    CLIENT_ID = settings.GDRIVE_CLIENT_ID
    CLIENT_SECRET = settings.GDRIVE_CLIENT_SECRET
    REFRESH_TOKEN = settings.GDRIVE_REFRESH_TOKEN

    def __init__(self):
        self.service = None
        logger.info("Authentication: Initializing with OAuth Refresh Token...")
        
        try:
            # Create credentials object using the refresh token
            creds = Credentials(
                None, 
                refresh_token=self.REFRESH_TOKEN,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.CLIENT_ID,
                client_secret=self.CLIENT_SECRET,
                scopes=self.SCOPES
            )
            
            # Verify/Refresh the token immediately
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Authentication successful. Drive service created.")
            
        except Exception as e:
            logger.error(f"Critical Error: Failed to authenticate GDrive: {e}")
            raise

    def _get_or_create_folder(self, folder_name, parent_id):
        try:
            query = (f"mimeType='application/vnd.google-apps.folder' "
                     f"and name='{folder_name}' "
                     f"and '{parent_id}' in parents "
                     f"and trashed=false")
            
            results = self.service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])

            if files:
                return files[0]['id']
            else:
                file_metadata = {
                    'name': folder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_id]
                }
                folder = self.service.files().create(body=file_metadata, fields='id').execute()
                logger.info(f"Created new folder '{folder_name}' (ID: {folder.get('id')})")
                return folder.get('id')

        except HttpError as e:
            logger.error(f"GDrive API Error in _get_or_create_folder: {e}")
            raise

    def _upload_file_content(self, file_name, content, parent_id):
        try:
            # 1. Check if file exists to overwrite
            query = (f"name='{file_name}' and '{parent_id}' in parents and trashed=false")
            results = self.service.files().list(q=query, fields="files(id)").execute()
            for file in results.get('files', []):
                self.service.files().delete(fileId=file['id']).execute()

            # 2. Prepare content
            if isinstance(content, str):
                media = MediaIoBaseUpload(io.BytesIO(content.encode('utf-8')), mimetype='text/plain', resumable=True)
            else:
                media = MediaIoBaseUpload(io.BytesIO(content), mimetype='application/octet-stream', resumable=True)

            # 3. Upload
            file_metadata = {'name': file_name, 'parents': [parent_id]}
            file = self.service.files().create(body=file_metadata, media_body=media, fields='id').execute()
            return file.get('id')
            
        except HttpError as e:
            logger.error(f"Failed to upload file {file_name}: {e}")
            raise

    def upload_file(self, db_problem_id, file_name, content):
        """Generic uploader for auxiliary files."""
        try:
            problem_folder_id = self._get_or_create_folder(str(db_problem_id), self.ROOT_FOLDER_ID)
            self._upload_file_content(file_name, content, problem_folder_id)
            logger.info(f"Uploaded {file_name} to problem folder {db_problem_id}")
        except Exception as e:
            logger.error(f"Error uploading {file_name} for problem {db_problem_id}: {e}")

    def upload_test_case(self, db_problem_id, test_number, input_data, output_data):
        """Uploads a single test case (sequential)."""
        try:
            problem_folder_id = self._get_or_create_folder(str(db_problem_id), self.ROOT_FOLDER_ID)
            input_filename = f"{test_number:02d}"
            output_filename = f"{test_number:02d}.a"

            self._upload_file_content(input_filename, input_data, problem_folder_id)
            self._upload_file_content(output_filename, output_data, problem_folder_id)
            logger.info(f"Uploaded test #{test_number} for problem {db_problem_id}")

        except Exception as e:
            logger.error(f"Error uploading test case #{test_number} for problem {db_problem_id}: {e}")

    def upload_batch_test_cases(self, db_problem_id, test_cases_list):
        """
        Uploads multiple test cases in parallel for a specific problem.
        
        Args:
            db_problem_id (str|int): The database problem ID.
            test_cases_list (list): A list of dictionaries containing test data.
                                    Format: [{'input': '...', 'output': '...'}, ...]
        """
        try:
            # 1. Ensure folder exists ONCE to save API calls
            problem_folder_id = self._get_or_create_folder(str(db_problem_id), self.ROOT_FOLDER_ID)
            
            logger.info(f"Starting batch upload for {len(test_cases_list)} cases to problem {db_problem_id}...")

            # 2. Define the worker function for a single test case
            def upload_worker(index, data):
                test_num = index + 1
                input_filename = f"{test_num:02d}"
                output_filename = f"{test_num:02d}.a"
                
                try:
                    # Upload Input
                    self._upload_file_content(input_filename, data['input'], problem_folder_id)
                    # Upload Output
                    self._upload_file_content(output_filename, data['output'], problem_folder_id)
                    return f"Test #{test_num}: Success"
                except Exception as exc:
                    return f"Test #{test_num}: Failed - {exc}"

            # 3. Use ThreadPoolExecutor to run uploads in parallel
            # max_workers=8 is usually a safe limit for GDrive API without hitting rate limits instantly
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                # Prepare futures
                futures = {
                    executor.submit(upload_worker, i, tc): i 
                    for i, tc in enumerate(test_cases_list)
                }
                
                # Wait for completion and log results
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    logger.debug(result)

            logger.info(f"Batch upload completed for problem {db_problem_id}")

        except Exception as e:
            logger.error(f"Error in batch upload for problem {db_problem_id}: {e}")

    def empty_blob(self, problem_id):
        """Deletes the folder for a specific problem_id."""
        try:
            query_prob = (f"name='{problem_id}' and '{self.ROOT_FOLDER_ID}' in parents and trashed=false")
            results_prob = self.service.files().list(q=query_prob, fields="files(id)").execute()
            prob_folders = results_prob.get('files', [])

            if not prob_folders:
                logger.warning(f"No folder found for problem {problem_id} inside root.")
                return

            for folder in prob_folders:
                logger.info(f"Deleting folder: {problem_id} (ID: {folder['id']})")
                self.service.files().delete(fileId=folder['id']).execute()
            
            logger.info(f"Cleaned up data for problem {problem_id}.")

        except Exception as e:
            logger.error(f"Error cleaning up problem {problem_id}: {e}")