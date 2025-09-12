from supabase import create_client
import os
import io
import uuid
import mimetypes
from dotenv import load_dotenv
import time

load_dotenv()

# Initialize Supabase client
def get_supabase_client():
    """Create and return a Supabase client with retry logic"""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print("Error: Supabase credentials not found in environment variables")
        return None
    
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            client = create_client(supabase_url, supabase_key)
            # Test the connection
            client.table('users').select('*').limit(1).execute()
            return client
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Supabase connection attempt {attempt+1} failed: {str(e)}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Failed to connect to Supabase after {max_retries} attempts: {str(e)}")
                # Return None or raise an exception based on your error handling strategy
                return None

# Storage functions for uploads and results
def upload_file_to_storage(file_path, bucket_name='uploads'):
    """
    Upload a file to Supabase storage
    :param file_path: Local path to the file
    :param bucket_name: 'uploads' or 'results'
    :return: URL to the uploaded file or None if failed
    """
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        # Generate a unique file name to avoid collisions
        file_name = os.path.basename(file_path)
        unique_name = f"{uuid.uuid4().hex}_{file_name}"
        
        # Guess the MIME type based on file extension
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'application/octet-stream'  # Default MIME type
        
        # Read the file
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Upload to Supabase Storage - just try the upload and handle errors with try/except
        try:
            supabase.storage.from_(bucket_name).upload(
                unique_name,
                file_content,
                {"content-type": content_type}
            )
        except Exception as upload_error:
            print(f"Error during storage upload: {str(upload_error)}")
            return None
        
        # Generate public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(unique_name)
        return public_url
    except Exception as e:
        print(f"Error uploading file to storage: {str(e)}")
        return None

def upload_bytes_to_storage(file_bytes, file_name, content_type, bucket_name='results'):
    """
    Upload bytes directly to Supabase storage (for in-memory files like PDFs)
    :param file_bytes: Bytes of the file content
    :param file_name: Name to give the file
    :param content_type: MIME type of the file
    :param bucket_name: 'uploads' or 'results'
    :return: URL to the uploaded file or None if failed
    """
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        # Generate a unique file name to avoid collisions
        unique_name = f"{uuid.uuid4().hex}_{file_name}"
        
        # Upload bytes to Supabase Storage - just try the upload and handle errors with try/except
        try:
            supabase.storage.from_(bucket_name).upload(
                unique_name,
                file_bytes,
                {"content-type": content_type}
            )
        except Exception as upload_error:
            print(f"Error during storage upload: {str(upload_error)}")
            return None
        
        # Generate public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(unique_name)
        return public_url
    except Exception as e:
        print(f"Error uploading bytes to storage: {str(e)}")
        return None

def download_file_from_storage(file_name, bucket_name='uploads'):
    """
    Download a file from Supabase storage
    :param file_name: Name of the file in the bucket
    :param bucket_name: 'uploads' or 'results'
    :return: Bytes of the file or None if failed
    """
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        # Download from Supabase Storage
        response = supabase.storage.from_(bucket_name).download(file_name)
        
        if not response:
            print(f"Error downloading file {file_name}")
            return None
        
        return response
    except Exception as e:
        print(f"Error downloading file from storage: {str(e)}")
        return None

def list_files_in_storage(bucket_name='uploads', path=None):
    """
    List files in a Supabase storage bucket
    :param bucket_name: 'uploads' or 'results'
    :param path: Optional path prefix to filter files
    :return: List of file objects or empty list if failed
    """
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        # List files in the bucket, optionally filtering by path
        response = supabase.storage.from_(bucket_name).list(path or '')
        return response if response else []
    except Exception as e:
        print(f"Error listing files in storage: {str(e)}")
        return []

def delete_file_from_storage(file_name, bucket_name='uploads'):
    """
    Delete a file from Supabase storage
    :param file_name: Name of the file in the bucket
    :param bucket_name: 'uploads' or 'results'
    :return: True if successful, False otherwise
    """
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # Delete from Supabase Storage
        supabase.storage.from_(bucket_name).remove([file_name])
        return True
    except Exception as e:
        print(f"Error deleting file from storage: {str(e)}")
        return False

# User management functions
def get_user(user_id):
    """Get user data by user_id"""
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        response = supabase.table('users').select('*').eq('user_id', user_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting user: {str(e)}")
        return None

def create_user(user_data):
    """Create a new user in the database"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        response = supabase.table('users').insert(user_data).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error creating user: {str(e)}")
        return False

def update_user(user_id, user_data):
    """Update user data"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        response = supabase.table('users').update(user_data).eq('user_id', user_id).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error updating user: {str(e)}")
        return False

# Subscription management functions
def get_subscription(user_id):
    """Get subscription data for a user"""
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        response = supabase.table('subscriptions').select('*').eq('user_id', user_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting subscription: {str(e)}")
        return None

def create_subscription(subscription_data):
    """Create a new subscription"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        response = supabase.table('subscriptions').insert(subscription_data).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error creating subscription: {str(e)}")
        return False

def update_subscription(subscription_id, subscription_data):
    """Update subscription data"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        response = supabase.table('subscriptions').update(subscription_data).eq('id', subscription_id).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error updating subscription: {str(e)}")
        return False

# Review tracking functions
def log_review(review_data):
    """Log a review in the database"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        response = supabase.table('reviews').insert(review_data).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error logging review: {str(e)}")
        return False

def get_user_reviews(user_id):
    """Get all reviews for a user"""
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        response = supabase.table('reviews').select('*').eq('user_id', user_id).execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting user reviews: {str(e)}")
        return []

def check_subscription_limit(user_id):
    """Check if user has remaining reviews in their plan"""
    # Rate limiting removed - always allow reviews for all users
    return True

def fix_upload_file_to_storage(file_path, bucket_name='uploads'):
    """
    Fixed version of upload_file_to_storage that doesn't use .get() on Response
    """
    supabase = get_supabase_client()
    if not supabase:
        return None
    
    try:
        # Generate a unique file name to avoid collisions
        file_name = os.path.basename(file_path)
        unique_name = f"{uuid.uuid4().hex}_{file_name}"
        
        # Guess the MIME type based on file extension
        content_type, _ = mimetypes.guess_type(file_path)
        if not content_type:
            content_type = 'application/octet-stream'  # Default MIME type
        
        # Read the file
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Upload to Supabase Storage - just try the upload and handle errors with try/except
        try:
            supabase.storage.from_(bucket_name).upload(
                unique_name,
                file_content,
                {"content-type": content_type}
            )
        except Exception as upload_error:
            print(f"Error during storage upload: {str(upload_error)}")
            return None
        
        # Generate public URL
        public_url = supabase.storage.from_(bucket_name).get_public_url(unique_name)
        return public_url
    except Exception as e:
        print(f"Error uploading file to storage: {str(e)}")
        return None

def ensure_storage_buckets():
    """Ensure required storage buckets exist and are properly configured"""
    supabase = get_supabase_client()
    if not supabase:
        print("Error: Could not connect to Supabase")
        return False
    
    try:
        # List existing buckets - with error handling for different Supabase versions
        try:
            buckets = supabase.storage.list_buckets()
            # Handle different return formats from different versions of supabase-py
            if hasattr(buckets, 'data'):
                existing_buckets = [bucket['name'] for bucket in buckets.data] if buckets.data else []
            elif isinstance(buckets, list):
                existing_buckets = [bucket['name'] for bucket in buckets] if buckets else []
            else:
                # Can't determine buckets, assume they don't exist
                existing_buckets = []
                print("Warning: Could not determine existing buckets format")
        except AttributeError as e:
            # Handle the case where buckets is not subscriptable
            print(f"Warning: Error listing buckets ({str(e)}), assuming buckets don't exist")
            existing_buckets = []
        
        # Create uploads bucket if it doesn't exist
        if 'uploads' not in existing_buckets:
            try:
                supabase.storage.create_bucket('uploads', {'public': True})
                print("Created 'uploads' bucket")
            except Exception as bucket_error:
                print(f"Error creating uploads bucket: {str(bucket_error)}")
        
        # Create results bucket if it doesn't exist
        if 'results' not in existing_buckets:
            try:
                supabase.storage.create_bucket('results', {'public': True})
                print("Created 'results' bucket")
            except Exception as bucket_error:
                print(f"Error creating results bucket: {str(bucket_error)}")
        
        return True
    except Exception as e:
        print(f"Error ensuring storage buckets: {str(e)}")
        return False

def get_all_users():
    """Get all users from the database for admin panel"""
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        response = supabase.table('users').select('*').execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting all users: {str(e)}")
        return []

def get_all_subscriptions():
    """Get all subscriptions from the database for admin panel"""
    supabase = get_supabase_client()
    if not supabase:
        return []
    
    try:
        response = supabase.table('subscriptions').select('*').execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting all subscriptions: {str(e)}")
        return []

def update_user_subscription(user_id, subscription_data):
    """Update a user's subscription by user_id"""
    supabase = get_supabase_client()
    if not supabase:
        return False
    
    try:
        # First get the subscription id for this user
        response = supabase.table('subscriptions').select('id').eq('user_id', user_id).execute()
        if not response.data or len(response.data) == 0:
            # No subscription found, create one
            subscription_data['user_id'] = user_id
            return create_subscription(subscription_data)
        
        # Update existing subscription
        subscription_id = response.data[0]['id']
        response = supabase.table('subscriptions').update(subscription_data).eq('id', subscription_id).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error updating user subscription: {str(e)}")
        return False

# Call this function when the application starts
ensure_storage_buckets()
