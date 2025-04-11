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
    # If no user_id is provided, allow the review (for anonymous users)
    if not user_id:
        return True
        
    # Set up retry parameters
    max_retries = 3
    retry_delay = 1  # Initial delay in seconds
    
    for attempt in range(max_retries):
        try:
            # Get user's subscription
            subscription = get_subscription(user_id)
            if not subscription:
                # No subscription found, use default limit
                return True
                
            # Check if subscription is active
            if subscription.get('status') != 'active':
                return False
                
            # Check for unlimited plan
            if subscription.get('plan_type') == 'unlimited':
                return True
                
            # Check usage against limit
            max_reviews = subscription.get('max_reviews', 0)
            if max_reviews <= 0:  # No limit or invalid value
                return True
                
            # Count reviews in current period
            current_period_start = subscription.get('current_period_start')
            current_period_end = subscription.get('current_period_end')
            
            if not current_period_start or not current_period_end:
                return True
                
            reviews = get_user_reviews(user_id)
            reviews_in_period = [
                r for r in reviews 
                if r.get('created_at') and current_period_start <= r.get('created_at') <= current_period_end
            ]
            
            return len(reviews_in_period) < max_reviews
            
        except Exception as e:
            if 'rate limit' in str(e).lower() and attempt < max_retries - 1:
                print(f"Rate limit hit when checking subscription. Retrying in {retry_delay} seconds... (Attempt {attempt+1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Error checking subscription limit: {str(e)}")
                # Default to allowing reviews if there's an error
                return True
    
    # If we've exhausted retries due to rate limits
    print("Exhausted retries when checking subscription limits.")
    return True  # Allow the review as a fallback

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
