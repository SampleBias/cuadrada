from flask import Flask, render_template, request, send_file, url_for, redirect, jsonify, session, flash, Response
import os
from werkzeug.utils import secure_filename
import uuid
from datetime import datetime, timedelta
from agents import (
    ClaudeAgent
)
from dotenv import load_dotenv
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import json
from collections import defaultdict
import random
import stripe
import zipfile
import io
import traceback
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
import requests
import time
from supabase_db import (
    get_user, create_user, update_user,
    get_subscription, create_subscription, update_subscription,
    log_review, get_user_reviews, check_subscription_limit,
    upload_file_to_storage, upload_bytes_to_storage,
    download_file_from_storage, list_files_in_storage, delete_file_from_storage,
    fix_upload_file_to_storage, ensure_storage_buckets,
    get_all_users, get_all_subscriptions, update_user_subscription
)
from functools import wraps
import threading
import queue
import pickle
import os.path
import re

load_dotenv()  # Load environment variables from .env file

# Global variable to store review results
review_results = {}

# Functions to manage persistent review_results
def save_review_results():
    """Save review results to a file to persist across app restarts"""
    try:
        # Save to a file in the tmp directory for Heroku
        if 'DYNO' in os.environ:
            save_path = '/tmp/review_results.pickle'
        else:
            save_path = os.path.join(os.path.dirname(__file__), 'review_results.pickle')
        
        with open(save_path, 'wb') as f:
            pickle.dump(review_results, f)
        print(f"Saved review results to {save_path}")
    except Exception as e:
        print(f"Error saving review results: {str(e)}")
        traceback.print_exc()

def load_review_results():
    """Load review results from a file if it exists"""
    global review_results
    try:
        # Load from a file in the tmp directory for Heroku
        if 'DYNO' in os.environ:
            load_path = '/tmp/review_results.pickle'
        else:
            load_path = os.path.join(os.path.dirname(__file__), 'review_results.pickle')
        
        if os.path.exists(load_path):
            with open(load_path, 'rb') as f:
                loaded_results = pickle.load(f)
                if isinstance(loaded_results, dict):
                    review_results = loaded_results
                    print(f"Loaded {len(review_results)} review results from {load_path}")
    except Exception as e:
        print(f"Error loading review results: {str(e)}")
        traceback.print_exc()

# Access the API keys
claude_api_key = os.getenv('CLAUDE_API_KEY')
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
auth0_domain = os.getenv('AUTH0_DOMAIN')
auth0_client_id = os.getenv('AUTH0_CLIENT_ID')
auth0_client_secret = os.getenv('AUTH0_CLIENT_SECRET')
auth0_callback_url = os.getenv('AUTH0_CALLBACK_URL', 'http://localhost:5000/callback')

app = Flask(__name__)
# Use a fixed secret key for production or get from environment variable
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'cuadrada-secure-key-for-sessions-2025')

# Configure session for production
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

# Load saved review results
load_review_results()

# Increase session lifetime (default is 31 days)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Initialize storage buckets and check connection
if not ensure_storage_buckets():
    print("WARNING: Failed to initialize Supabase storage buckets. File uploads may not work.")

# Auth0 setup
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=auth0_client_id,
    client_secret=auth0_client_secret,
    api_base_url=f'https://{auth0_domain}',
    access_token_url=f'https://{auth0_domain}/oauth/token',
    authorize_url=f'https://{auth0_domain}/authorize',
    server_metadata_url=f'https://{auth0_domain}/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid profile email',
        'audience': f'https://{auth0_domain}/api/v2/',
    },
)

# Configuration
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['RESULTS_FOLDER'] = os.getenv('RESULTS_FOLDER', 'results')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'pdf'}

# Create necessary folders - use absolute paths on Heroku
for folder in [app.config['UPLOAD_FOLDER'], app.config['RESULTS_FOLDER']]:
    # If we're on Heroku, use /tmp for file storage
    if 'DYNO' in os.environ:
        folder_path = os.path.join('/tmp', folder)
    else:
        folder_path = os.path.join(os.path.dirname(__file__), folder)
    
    os.makedirs(folder_path, exist_ok=True)
    # Make sure folder path is updated in config
    if folder == app.config['UPLOAD_FOLDER']:
        app.config['UPLOAD_FOLDER'] = folder_path
    else:
        app.config['RESULTS_FOLDER'] = folder_path

# Academic paper validation constants
ACADEMIC_INDICATORS = [
    "ABSTRACT", 
    "INTRODUCTION", 
    "METHODOLOGY", 
    "METHODS",
    "RESULTS", 
    "DISCUSSION", 
    "CONCLUSION", 
    "REFERENCES",
    "LITERATURE REVIEW",
    "BACKGROUND",
    "FINDINGS",
    "ANALYSIS"
]

# Admin panel settings
ADMIN_CODE = os.getenv('ADMIN_CODE', '123456')  # Default 6-digit code, should be changed in .env
ADMIN_EMAILS = ['james.utley@syndicate-labs.io', 'jamesutleyhm@gmail.com']

# Task queue for background processing
task_queue = queue.Queue()

# Start a worker thread to process tasks in the background
def background_worker():
    """Process tasks from the queue in the background"""
    print("Starting background worker thread...")
    
    while True:
        try:
            # Get task from queue with a timeout
            task = task_queue.get(timeout=1.0)
            
            # Extract function and arguments
            func = task.get('func')
            args = task.get('args', [])
            
            if func:
                try:
                    print(f"Processing task: {func.__name__} with args: {args}")
                    # Execute the function with arguments
                    func(*args)
                    print(f"Task {func.__name__} completed successfully")
                except Exception as e:
                    error_msg = f"Error executing task {func.__name__}: {str(e)}"
                    print(error_msg)
                    traceback.print_exc()
                    
                    # If this is a review processing task, update the review_results with the error
                    if func.__name__ == 'process_reviews' and len(args) >= 2:
                        submission_id = args[1]  # Second argument is submission_id
                        if submission_id in review_results:
                            review_results[submission_id]['error'] = error_msg
                            review_results[submission_id]['processing_complete'] = True
                            save_review_results()
                            print(f"Updated review_results with error for submission {submission_id}")
                finally:
                    # Mark the task as done
                    task_queue.task_done()
        except queue.Empty:
            # No tasks in queue, just continue
            pass
        except Exception as e:
            # Log any unexpected errors in the worker thread
            print(f"Unexpected error in background worker: {str(e)}")
            traceback.print_exc()
            
            # Small sleep to prevent CPU spinning on repeated errors
            time.sleep(0.5)

# Start the background worker thread
worker_thread = threading.Thread(target=background_worker, daemon=True)
worker_thread.start()

def admin_required(f):
    """Decorator to check if user is admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is logged in
        if not session.get('logged_in'):
            return redirect(url_for('admin_login'))
            
        # Check if user has admin session
        if not session.get('is_admin'):
            # Check if email is in admin list
            user_email = session.get('profile', {}).get('email', '')
            if user_email not in ADMIN_EMAILS:
                return redirect(url_for('admin_login'))
            return redirect(url_for('admin_verify'))
            
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename():
    """Generate a unique filename with date prefix"""
    return f"{datetime.now().strftime('%Y%m%d')}_{str(uuid.uuid4())[:8]}"

def format_error_message(error_str):
    """Convert technical error messages to user-friendly ones"""
    if 'rate_limit_error' in error_str.lower() or 'rate limit' in error_str.lower():
        return "Our review system is currently busy. The system attempted to use alternative models but was still rate limited. Please wait 60 seconds and try again."
    elif 'authentication_error' in error_str.lower() or 'invalid x-api-key' in error_str.lower():
        return "There was an issue with our review system authentication. Please contact support."
    elif 'failed to generate review after' in error_str.lower():
        return "Our AI review system is experiencing high demand. We tried multiple models but couldn't complete your review. Please try again in a few minutes."
    else:
        return "An unexpected error occurred. Please try again or contact support if the issue persists."

def is_valid_academic_paper(review_text):
    """Check if the text appears to be from a valid academic paper"""
    # Count how many academic paper structural elements exist
    academic_element_count = sum(1 for indicator in ACADEMIC_INDICATORS if indicator in review_text.upper())
    
    # Check if citations exist in the text (look for common citation patterns)
    has_citations = any(pattern in review_text for pattern in ["et al.", "(19", "(20", "[", "REFERENCES"])
    
    # Only consider it an academic paper if it has enough academic elements and citations
    return academic_element_count >= 3 and has_citations

def parse_criteria_scores(review_text):
    """Parse the review text for individual criteria scores. Returns a dict of {criterion: score}."""
    import re
    # Define the criteria and their weights
    criteria = {
        'Methodology': 0.20,
        'Novelty': 0.20,
        'Technical Depth': 0.15,
        'Clarity': 0.15,
        'Literature Review': 0.15,
        'Impact': 0.15
    }
    scores = {}
    for criterion in criteria:
        # Look for lines like "Methodology: 85%" or "Methodology (20%): 85%"
        match = re.search(rf'{criterion}[^\d]{{0,20}}(\d{{1,3}})%', review_text, re.IGNORECASE)
        if match:
            score = int(match.group(1))
            scores[criterion] = score
    return scores

def determine_paper_decision(review_text):
    """Determine the decision and acceptance status from review text. Applies strength bonus if eligible."""
    # Check for known indicators of a good vs bad paper
    is_accepted = False
    final_score = None
    # First check for explicit decision in text
    if re.search(r'FINAL DECISION:\s*\*\*ACCEPTED\*\*', review_text, re.IGNORECASE):
        decision = "ACCEPTED"
        is_accepted = True
    elif re.search(r'FINAL DECISION:\s*\*\*ACCEPTED WITH (MINOR|MAJOR) REVISION', review_text, re.IGNORECASE):
        decision = "REVISION"
        is_accepted = False
    elif re.search(r'FINAL DECISION:\s*\*\*REJECTED\*\*', review_text, re.IGNORECASE):
        decision = "REJECTED"
        is_accepted = False
    # If no explicit decision, determine based on content and keywords
    elif ("accepted" in review_text.lower() and not "rejected" in review_text.lower()) or ("recommend publication" in review_text.lower()):
        decision = "ACCEPTED"
        is_accepted = True
    elif "revision" in review_text.lower() or "revise" in review_text.lower() or "improvements needed" in review_text.lower():
        decision = "REVISION"
    elif "reject" in review_text.lower():
        decision = "REJECTED"
    else:
        decision = "REVISION"

    # Parse criteria scores and calculate weighted score
    criteria_weights = {
        'Methodology': 0.20,
        'Novelty': 0.20,
        'Technical Depth': 0.15,
        'Clarity': 0.15,
        'Literature Review': 0.15,
        'Impact': 0.15
    }
    scores = parse_criteria_scores(review_text)
    if scores:
        weighted_score = sum(scores.get(crit, 0) * weight for crit, weight in criteria_weights.items())
        # Check for strength bonus: any two criteria >80%
        strong_criteria = [crit for crit, score in scores.items() if score > 80]
        if len(strong_criteria) >= 2:
            weighted_score = min(weighted_score * 1.05, 100)  # Cap at 100%
        final_score = round(weighted_score, 2)
    else:
        final_score = None

    # Make sure summary is defined
    if 'summary' not in locals():
        summary = review_text.split('\n\n')[0] if '\n\n' in review_text else review_text

    # Truncate summary if too long
    truncated_summary = summary[:300] + '...' if len(summary) > 300 else summary

    # Truncate full review for UI display
    full_review = review_text[:1000] + "..." if len(review_text) > 1000 else review_text

    return {
        "decision": decision,
        "summary": truncated_summary,
        "full_review": full_review,
        "accepted": is_accepted,
        "final_score": final_score,
        "criteria_scores": scores
    }

def generate_certificate(paper_title, submission_id):
    """Generate a properly formatted PDF certificate"""
    certificate_filename = f"{submission_id}_certificate.pdf"
    # Create a temporary certificate path for generation
    certificate_path = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'], certificate_filename)
    
    try:
        c = canvas.Canvas(certificate_path, pagesize=letter)
        width, height = letter

        # Add certificate styling
        c.setFillColorRGB(0.5, 0, 0.5)  # Purple to match Cuadrada branding
        c.setFont("Helvetica-Bold", 30)
        c.drawCentredString(width/2, height-2*inch, "Certificate of Acceptance")
        
        # Add branded square logo to top right
        square_size = 0.75*inch
        square_margin = 0.75*inch
        # Draw square outline
        c.setStrokeColorRGB(0.5, 0, 0.5)  # Purple to match branding (#800080)
        c.setLineWidth(5)
        c.rect(width-square_margin-square_size, height-square_margin-square_size, 
               square_size, square_size, fill=0)
        
        # Add content with error handling for long titles
        try:
            # Title wrapping with max width check
            max_width = width - 2*inch
            title_lines = []
            current_line = []
            
            for word in paper_title.split():
                current_line.append(word)
                if c.stringWidth(' '.join(current_line), "Helvetica-Bold", 14) > max_width:
                    title_lines.append(' '.join(current_line[:-1]))
                    current_line = [word]
            if current_line:
                title_lines.append(' '.join(current_line))
            
            # Draw title lines
            y_position = height-3.5*inch
            for line in title_lines:
                c.drawCentredString(width/2, y_position, line)
                y_position -= 20

            # Add remaining content
            c.drawCentredString(width/2, y_position-1*inch, "has successfully passed Cuadrada's")
            c.drawCentredString(width/2, y_position-1.5*inch, "AI-powered peer review process")
            
            # Add metadata
            c.setFont("Helvetica", 12)
            c.drawCentredString(width/2, height-6.5*inch, f"Date: {datetime.now().strftime('%B %d, %Y')}")
            c.drawCentredString(width/2, height-7*inch, f"Certificate ID: {submission_id}")
            
            c.save()
            
            # Upload the certificate to Supabase storage
            public_url = upload_file_to_storage(certificate_path, 'results')
            
            # Store the URL in the session for later retrieval
            if public_url:
                session['certificate_url'] = public_url
            
            return certificate_filename
            
        except Exception as e:
            print(f"Error formatting certificate content: {str(e)}")
            raise
    except Exception as e:
        print(f"Error generating certificate: {str(e)}")
        raise

def generate_review_pdf(review_text, reviewer_name, submission_id):
    """Generate a properly formatted PDF review with Cuadrada branding"""
    result_filename = f"{submission_id}_{reviewer_name.replace(' ', '_')}.pdf"
    result_path = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'], result_filename)
    
    try:
        c = canvas.Canvas(result_path, pagesize=letter)
        width, height = letter
        
        # Add header with logo and styling
        c.setFillColorRGB(0.5, 0, 0.5)  # Purple to match Cuadrada branding
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width/2, height-1*inch, "Cuadrada Peer Review")
        
        # Add reviewer info
        c.setFont("Helvetica-Bold", 14)
        c.drawString(1*inch, height-1.5*inch, f"Reviewer: {reviewer_name}")
        c.drawString(1*inch, height-1.75*inch, f"Date: {datetime.now().strftime('%B %d, %Y')}")
        c.drawString(1*inch, height-2*inch, f"Submission ID: {submission_id}")
        
        # Add separator line
        c.setStrokeColorRGB(0.5, 0, 0.5)
        c.line(1*inch, height-2.25*inch, width-1*inch, height-2.25*inch)
        
        # Add review content with text wrapping
        c.setFont("Helvetica", 12)
        text_object = c.beginText()
        text_object.setTextOrigin(1*inch, height-2.5*inch)
        
        # Wrap text to fit page width
        words = review_text.split()
        line = []
        for word in words:
            line.append(word)
            line_width = c.stringWidth(' '.join(line), "Helvetica", 12)
            if line_width > width - 144:  # 72 points margin on each side
                text_object.textLine(' '.join(line[:-1]))
                line = [word]
                
                # Check if we need a new page
                if text_object.getY() < 72:
                    c.drawText(text_object)
                    c.showPage()
                    text_object = c.beginText()
                    text_object.setTextOrigin(72, height - 72)
                    c.setFont("Helvetica", 12)
        
        if line:
            text_object.textLine(' '.join(line))
        
        c.drawText(text_object)
        c.save()
        
        # Upload the review to Supabase storage
        public_url = upload_file_to_storage(result_path, 'results')
        
        # Store the URL in the review data
        if public_url and reviewer_name in session.get('review_results', {}):
            session['review_results'][reviewer_name]['file_url'] = public_url
        
        return result_filename
    
    except Exception as e:
        print(f"Error generating review PDF: {str(e)}")
        return None

def get_file_download_name(filename, paper_title=None):
    """Generate a user-friendly download filename"""
    if not paper_title:
        paper_title = 'Research_Paper'
        
    date_time_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    
    # Determine file type (report or certificate)
    if '_certificate' in filename:
        download_name = f"{paper_title}_Certificate_{date_time_str}.pdf"
    else:
        # Extract reviewer name from filename if available
        reviewer_name = "Review"
        if '_' in filename:
            parts = filename.split('_')
            if len(parts) > 1 and parts[1] != 'certificate.pdf':
                reviewer_name = parts[1]
        
        download_name = f"{paper_title}_{reviewer_name}_{date_time_str}.pdf"
    
    # Ensure the filename is safe
    return secure_filename(download_name)

def analyze_paper_with_agent(agent, filepath, reviewer_name, submission_id):
    """Analyze a paper with a specific agent and process the result"""
    try:
        # Track original model and potential fallbacks
        original_model = agent.current_model
        review_text = agent.analyze_paper(filepath)
        
        # Check if model was downgraded during processing
        final_model = agent.current_model
        model_downgraded = original_model != final_model
        
        if not review_text:
            raise ValueError(f"No review text generated by {reviewer_name}")
        
        # Determine decision and get summary
        result = determine_paper_decision(review_text)
        
        # Add model information if downgraded
        model_info = ""
        if model_downgraded:
            model_info = f" [Note: Review generated using fallback model {final_model} due to rate limiting]"
        
        # Build result object without generating PDF (to be done later in request context)
        return {
            'decision': result['decision'],
            'summary': result['summary'] + (model_info if model_downgraded else ""),
            'full_review': review_text + (model_info if model_downgraded else ""),
            'accepted': result['accepted'],
            'model_used': final_model,
            'model_downgraded': model_downgraded
        }
    
    except Exception as e:
        print(f"Error in analysis with {reviewer_name}: {str(e)}")
        error_message = format_error_message(str(e))
        return {
            'decision': 'ERROR',
            'summary': error_message,
            'full_review': error_message,
            'accepted': False,
            'model_used': agent.current_model if hasattr(agent, 'current_model') else 'unknown'
        }

def get_leaderboard_data():
    """Get top researchers data for the leaderboard"""
    researchers = [
        {"name": "Dr. Sarah Chen", "papers": 42, "avatar": "chen.jpg"},
        {"name": "Prof. James Wilson", "papers": 38, "avatar": "wilson.jpg"},
        {"name": "Dr. Maria Garcia", "papers": 35, "avatar": "garcia.jpg"},
        {"name": "Dr. Alex Kumar", "papers": 31, "avatar": "kumar.jpg"},
        {"name": "Prof. Emma Thompson", "papers": 29, "avatar": "thompson.jpg"}
    ]
    return sorted(researchers, key=lambda x: x['papers'], reverse=True)

def find_file_with_secure_path(base_path, filename):
    """Find a file with secure path checking"""
    if not filename or '..' in filename:  # Prevent directory traversal
        return None
        
    file_path = os.path.join(base_path, secure_filename(filename))
    
    if os.path.exists(file_path):
        return file_path
        
    # Check if we have the file without spaces in reviewer name (alternative format)
    reviewer_parts = filename.split('_')
    if len(reviewer_parts) > 1:
        alt_filename = filename.replace(' ', '')
        alt_path = os.path.join(base_path, secure_filename(alt_filename))
        if os.path.exists(alt_path):
            return alt_path
            
    return None

@app.route('/login', methods=['GET'])
def login():
    """Route for login with Auth0"""
    # Ensure session is cleared before login
    session.clear()
    
    # Get callback URL from environment or use default
    callback_url = os.getenv('AUTH0_CALLBACK_URL', url_for('callback', _external=True))
    
    return auth0.authorize_redirect(
        redirect_uri=callback_url,
        audience=f'https://{auth0_domain}/api/v2/'
    )

@app.route('/callback')
def callback():
    """Auth0 callback handler"""
    try:
        # Make session permanent
        session.permanent = True
        
        # Get token from Auth0
        token = auth0.authorize_access_token()
        
        # Get user info
        resp = auth0.get('userinfo')
        userinfo = resp.json()
        
        # Store user info in session
        session['jwt_payload'] = userinfo
        session['profile'] = {
            'user_id': userinfo['sub'],
            'name': userinfo.get('name', ''),
            'picture': userinfo.get('picture', ''),
            'email': userinfo.get('email', '')
        }
        session['user_name'] = userinfo.get('name', '')
        session['user_avatar'] = userinfo.get('picture', '')
        session['logged_in'] = True
        
        # Check if user exists in Supabase, create if not
        user_id = userinfo['sub']
        user = get_user(user_id)
        
        if not user:
            # Create new user
            user_data = {
                'user_id': user_id,
                'email': userinfo.get('email', ''),
                'name': userinfo.get('name', ''),
                'created_at': datetime.now().isoformat()
            }
            create_user(user_data)
            
            # Create default subscription - now unlimited for all users
            subscription_data = {
                'user_id': user_id,
                'plan_type': 'unlimited',
                'status': 'active',
                'max_reviews': 999999,  # Unlimited reviews for all users
                'current_period_start': datetime.now().isoformat(),
                'current_period_end': (datetime.now() + timedelta(days=365)).isoformat()
            }
            create_subscription(subscription_data)
        
        return redirect(url_for('index'))
        
    except Exception as e:
        # Log the full error for debugging
        error_message = f"Auth0 login error: {str(e)}"
        print(error_message)
        traceback.print_exc()
        
        # Store error in session for display
        session['auth_error'] = error_message
        
        # Clear any other session data, preserving the error message
        for key in list(session.keys()):
            if key != 'auth_error':
                session.pop(key, None)
        
        return redirect(url_for('auth_error'))

@app.route('/auth_error')
def auth_error():
    """Error page for authentication failures"""
    return render_template('auth_error.html')

@app.route('/', methods=['GET'])
def index():
    # Check if user is logged in
    if not session.get('logged_in'):
        # Show login page instead of direct redirect
        return render_template('login_landing.html')
    
    # User is logged in, show the main page
    leaderboard = get_leaderboard_data()
    return render_template('index.html', leaderboard=leaderboard)

@app.route('/home')
def home():
    """Shortcut to redirect to index"""
    return redirect(url_for('index'))

def process_reviews(upload_path, submission_id, user_id, paper_title, filename):
    """Process reviews in the background"""
    global review_results
    
    try:
        print(f"Starting review processing for '{submission_id}'")
        
        # Process all reviewers in a list to track their decisions
        reviewers_to_process = ["Reviewer 1", "Reviewer 2", "Reviewer 3"]
        results = {}
        all_accepted = True  # Start with True, will set to False if any reviewer doesn't accept
        
        for reviewer_name in reviewers_to_process:
            agent = ClaudeAgent(model_index=1)  # Claude 3 Sonnet
            print(f"Processing {reviewer_name} for submission '{submission_id}'")
            result = analyze_paper_with_agent(agent, upload_path, reviewer_name, submission_id)
            
            # Store review results
            results[reviewer_name] = {
                'decision': result.get('decision', 'ERROR'),
                'summary': result.get('summary', 'Error generating review'),
                'full_review': result.get('full_review', 'Error generating review'),
                'model_used': result.get('model_used', 'unknown'),
                'model_downgraded': result.get('model_downgraded', False)
            }
            
            # Track if all reviewers have accepted the paper
            if result.get('decision') != 'ACCEPTED':
                all_accepted = False
                
            print(f"Completed {reviewer_name} with decision: {result.get('decision', 'ERROR')}")
        
        print(f"All reviews completed for submission '{submission_id}'. Updating global state.")
        print(f"All accepted: {all_accepted}")
        
        # CRITICAL FIX: Make sure we have the most up-to-date review_results
        try:
            # Load latest results from disk to avoid overwriting other changes
            loaded_results = load_review_results()
            if loaded_results:
                # Update our global with the loaded data first
                review_results = loaded_results
        except Exception as e:
            print(f"Error loading latest review results: {str(e)}")
        
        # Check if entry exists, create it if needed
        if submission_id not in review_results:
            print(f"Review results entry missing, creating new one for '{submission_id}'")
            review_results[submission_id] = {
                'results': {},
                'all_accepted': False,
                'processing_complete': False,
                'file_url': upload_path
            }
            
        # Store the results in the global dictionary (without generating PDFs)
        review_results[submission_id] = {
            'results': results,
            'all_accepted': all_accepted,  # Set based on our computation above
            'processing_complete': True,  # Mark as complete
            'needs_pdf_generation': True,  # Flag to generate PDFs later in a request context
            'file_url': upload_path  # Make sure we preserve the file URL
        }
        
        # Save to persistent storage
        print(f"Saving completed review results for '{submission_id}' to persistent storage")
        save_review_results()
        print(f"Review results saved. Current submission IDs: {list(review_results.keys())}")
        
        # EXTRA VERIFICATION - verify that the pickle file has the complete results
        try:
            verify_results = load_review_results()
            if (verify_results and submission_id in verify_results and 
                verify_results[submission_id].get('processing_complete', False)):
                print(f"Verified pickle file has complete results for '{submission_id}'")
            else:
                print(f"WARNING: Verification failed for '{submission_id}' in pickle file")
                # Let's try saving again to be sure
                save_review_results()
        except Exception as e:
            print(f"Error verifying results: {str(e)}")
        
        # Log the review in the database
        if user_id:
            review_data = {
                'user_id': user_id,
                'submission_id': submission_id,
                'paper_title': paper_title or filename,
                'decision': 'COMPLETED',
                'created_at': datetime.now().isoformat(),
                'file_url': upload_path
            }
            log_review(review_data)
            
        print(f"Completed processing reviews for submission {submission_id}")
        
    except Exception as e:
        print(f"Error processing reviews: {str(e)}")
        traceback.print_exc()
        
        # Store error information in the results
        review_results[submission_id] = {
            'error': str(e),
            'processing_complete': True,
            'file_url': upload_path  # Preserve file URL
        }
        
        # Save to persistent storage even on error
        save_review_results()

@app.route('/upload', methods=['POST'])
def upload_file():
    """Optimized upload handler that processes one reviewer at a time"""
    # Get user ID from session if available
    user_id = session.get('profile', {}).get('user_id', None)
    
    # Rate limiting removed - allow unlimited reviews for all users
    
    if 'paper' not in request.files:
        print("No file part in request")
        return redirect(url_for('index'))
    
    file = request.files['paper']
    if file.filename == '' or not allowed_file(file.filename):
        print(f"Invalid file: {file.filename}")
        return redirect(url_for('index'))
    
    try:
        submission_id = generate_unique_filename()
        print(f"Generated new submission ID: {submission_id}")
        filename = secure_filename(file.filename)
        
        # First save the file locally (this will be temporary)
        upload_path = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'], f"{submission_id}_{filename}")
        file.save(upload_path)
        print(f"File saved locally at: {upload_path}")
        
        # Upload to Supabase - using the fixed function
        file_url = fix_upload_file_to_storage(upload_path, 'uploads')
        
        if not file_url:
            print("Failed to upload file to Supabase storage")
            return jsonify({
                'error': 'Failed to upload file to storage. Please try again.'
            }), 403
        
        print(f"File uploaded to Supabase: {file_url}")
        
        # Store the file URL in the session
        session['upload_file_url'] = file_url
        session['submission_id'] = submission_id  # Store submission ID explicitly in session
        print(f"Stored submission ID '{submission_id}' in session")
        
        # Store the paper title in session for later use in download
        paper_title = request.form.get('paper_title', '')
        if paper_title:
            session['paper_title'] = paper_title
            print(f"Stored paper title in session: '{paper_title}'")
        else:
            # Use the filename as a fallback
            session['paper_title'] = os.path.splitext(filename)[0]
            print(f"No paper title provided, using filename: '{session['paper_title']}'")
        
        # Initialize review results for this submission
        review_results[submission_id] = {
            'results': {},
            'all_accepted': False,
            'processing_complete': False,
            'file_url': file_url
        }
        print(f"Initialized review_results for submission ID: '{submission_id}'")
        print(f"Available submission IDs: {list(review_results.keys())}")
        
        # Save to persistent storage
        save_review_results()
        
        # Log the review in the database as "processing"
        if user_id:
            review_data = {
                'user_id': user_id,
                'submission_id': submission_id,
                'paper_title': paper_title or filename,
                'decision': 'PROCESSING',
                'created_at': datetime.now().isoformat(),
                'file_url': file_url
            }
            log_review(review_data)
        
        # Process reviews in the background
        task = {
            'func': process_reviews,
            'args': [upload_path, submission_id, user_id, paper_title, filename]
        }
        task_queue.put(task)
        
        # Use the submission ID string not the variable
        submission_id_str = str(submission_id)  # Ensure it's a string
        print(f"Added review processing task to queue for submission {submission_id_str}")
        
        # Redirect to the review_results page instead of trying to render the template directly
        # This ensures we're using a proper route that can be refreshed
        return redirect(url_for('view_review_results', submission_id=submission_id_str))
            
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        traceback.print_exc()  # Print the full traceback for debugging
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    """Handle file downloads with proper error checking"""
    if not filename or '..' in filename:  # Prevent directory traversal
        return redirect(url_for('index'))
        
    try:
        # Get the results folder path for temporary storage
        results_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
        temp_path = os.path.join(results_dir, filename)
        
        # Get file URL from session based on filename
        file_url = None
        
        # Check if it's a review file
        submission_id = session.get('submission_id')
        if submission_id and filename.startswith(submission_id):
            for reviewer, result in session.get('review_results', {}).items():
                if f"{submission_id}_{reviewer.replace(' ', '_')}.pdf" == filename:
                    file_url = result.get('file_url')
                    break
        
        # Check if it's a certificate
        if not file_url and filename.endswith('_certificate.pdf'):
            file_url = session.get('certificate_url')
        
        if not file_url:
            print(f"No URL found for file: {filename}")
            return redirect(url_for('index'))
            
        # Download the file to a temporary location
        response = requests.get(file_url)
        if response.status_code != 200:
            print(f"Error downloading file from URL: {file_url}")
            return redirect(url_for('index'))
            
        # Save to temporary location
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        # Extract paper title from session if available
        paper_title = session.get('paper_title', 'Report')
        
        # Create a formatted filename
        download_name = get_file_download_name(filename, paper_title)
        
        # Send the file
        return send_file(
            temp_path,
            as_attachment=True,
            download_name=download_name
        )
    except Exception as e:
        print(f"Error downloading file: {str(e)}")
        return redirect(url_for('index'))

@app.route('/download_certificate')
def download_certificate():
    """Download the certificate for the current submission"""
    submission_id = session.get('submission_id')
    if not submission_id:
        return redirect(url_for('index'))
        
    try:
        # Get the results folder path for temporary storage
        results_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
        
        # Use certificate URL from session if available
        certificate_url = session.get('certificate_url')
        certificate_filename = session.get('certificate_filename')
        
        if certificate_url and certificate_filename:
            # Download from Supabase
            temp_path = os.path.join(results_dir, certificate_filename)
            
            # Download the file to a temporary location
            response = requests.get(certificate_url)
            if response.status_code != 200:
                return redirect(url_for('index'))
                
            # Save to temporary location
            with open(temp_path, 'wb') as f:
                f.write(response.content)
                
            # Extract paper title from session if available
            paper_title = session.get('paper_title', 'Research_Paper')
            
            # Create a formatted filename
            download_name = get_file_download_name(certificate_filename, paper_title)
            
            # Send the file
            return send_file(
                temp_path,
                as_attachment=True,
                download_name=download_name
            )
        else:
            return redirect(url_for('index'))
    except Exception as e:
        print(f"Error downloading certificate: {str(e)}")
        return redirect(url_for('index'))

@app.route('/retry_review/<submission_id>/<reviewer_name>', methods=['POST'])
def retry_review(submission_id, reviewer_name):
    try:
        # Get the upload file URL from session
        upload_file_url = session.get('upload_file_url')
        
        if not upload_file_url:
            # Fallback to finding the file on disk
            uploads_dir = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'])
            files = [f for f in os.listdir(uploads_dir) 
                    if f.startswith(submission_id)]
            
            if not files:
                return jsonify({'success': False, 'error': 'Original file not found'})
                
            upload_path = os.path.join(uploads_dir, files[0])
        else:
            # Download from Supabase to a temporary location
            uploads_dir = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'])
            temp_file = f"{submission_id}_temp.pdf"
            upload_path = os.path.join(uploads_dir, temp_file)
            
            # Download the file to a temporary location
            response = requests.get(upload_file_url)
            if response.status_code != 200:
                return jsonify({'success': False, 'error': 'Failed to download original file'})
                
            # Save to temporary location
            with open(upload_path, 'wb') as f:
                f.write(response.content)
        
        # Create new agent and analyze
        agent = ClaudeAgent(model_index=1)  # Start with Claude 3 Sonnet
        result = analyze_paper_with_agent(agent, upload_path, reviewer_name, submission_id)
        
        # Update session with new results (remove 'accepted' key since we don't store it)
        if 'accepted' in result:
            del result['accepted']
            
        if 'review_results' in session:
            session['review_results'][reviewer_name] = result
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"Error retrying review: {str(e)}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/summary/<submission_id>')
def view_summary(submission_id):
    try:
        # Count the different decisions
        stats = {'accepted': 0, 'revision': 0, 'rejected': 0}
        
        # Get results from session
        results = session.get('review_results', {})
        
        if not results:
            print("No review results found in session")
            return redirect(url_for('index'))
        
        for key, review in results.items():
            # Skip non-reviewer keys
            if not isinstance(review, dict):
                continue
                
            # Make sure the review has a decision field
            if 'decision' not in review:
                continue
                
            decision = review['decision']
            if decision == 'ACCEPTED':
                stats['accepted'] += 1
            elif decision == 'REVISION':
                stats['revision'] += 1
            elif decision == 'REJECTED':
                stats['rejected'] += 1
        
        print(f"Stats: {stats}")
        
        # Determine overall outcome - more positive messaging
        if stats['accepted'] >= 2:  # Relaxed criteria - only 2 acceptances needed
            outcome = {
                'class': 'accepted',
                'icon': '🌟',
                'title': 'Great Work!',
                'message': 'Congratulations! Your paper has been positively received by our reviewers. Your contribution to the field is valuable and appreciated.',
                'quote': '"Success is not the key to happiness. Happiness is the key to success. If you love what you are doing, you will be successful." - Albert Schweitzer'
            }
        elif stats['accepted'] >= 1:  # Even a single acceptance is highlighted positively
            outcome = {
                'class': 'revision',
                'icon': '✍️',
                'title': 'Almost There - Your Work Shows Promise!',
                'message': "Your paper has significant strengths and shows great potential. With a few adjustments based on the reviewers' suggestions, it will be even stronger!",
                'quote': '"The difference between ordinary and extraordinary is that little extra." - Jimmy Johnson'
            }
        elif stats['revision'] > 0:  # Focus on positive aspects of revision
            outcome = {
                'class': 'revision',
                'icon': '✨',
                'title': 'Your Work Has Potential!',
                'message': "The reviewers see value in your research and have provided feedback to enhance its impact. Consider their suggestions as opportunities to strengthen your work.",
                'quote': '"Feedback is the breakfast of champions." - Ken Blanchard'
            }
        else:
            outcome = {
                'class': 'rejected',
                'icon': '🚀',
                'title': 'A Stepping Stone to Success!',
                'message': "Every research journey has its challenges. The feedback provided offers valuable insights to refine and improve your work for future success. Don't be discouraged!",
                'quote': '"Success is not final, failure is not fatal: it is the courage to continue that counts." - Winston Churchill'
            }
        
        return render_template('summary.html',
                             stats=stats,
                             outcome_class=outcome['class'],
                             outcome_icon=outcome['icon'],
                             title=outcome['title'],
                             message=outcome['message'],
                             quote=outcome['quote'])
                             
    except Exception as e:
        print(f"Error generating summary: {str(e)}")
        return redirect(url_for('index'))

@app.route('/download_all/<submission_id>')
def download_all_reviews(submission_id):
    """Download all reviews for a submission as a zip file"""
    if not submission_id or '..' in submission_id:  # Prevent directory traversal
        return redirect(url_for('index'))
        
    try:
        # Create a zip file in memory
        memory_file = io.BytesIO()
        
        with zipfile.ZipFile(memory_file, 'w') as zf:
            # Get the review results from the session
            review_results = session.get('review_results', {})
            
            # Get the certificate URL if available
            certificate_url = session.get('certificate_url')
            certificate_filename = session.get('certificate_filename')
            
            # Temporary folder for downloads
            temp_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
            
            # Download and add each review file to the zip
            for reviewer, result in review_results.items():
                file_url = result.get('file_url')
                if file_url:
                    filename = f"{submission_id}_{reviewer.replace(' ', '_')}.pdf"
                    temp_path = os.path.join(temp_dir, filename)
                    
                    # Download the file to a temporary location
                    response = requests.get(file_url)
                    if response.status_code == 200:
                        # Save to temporary location
                        with open(temp_path, 'wb') as f:
                            f.write(response.content)
                        
                        # Add to zip
                        zf.write(temp_path, filename)
            
            # Add certificate if available
            if certificate_url and certificate_filename:
                temp_path = os.path.join(temp_dir, certificate_filename)
                
                # Download the file to a temporary location
                response = requests.get(certificate_url)
                if response.status_code == 200:
                    # Save to temporary location
                    with open(temp_path, 'wb') as f:
                        f.write(response.content)
                    
                    # Add to zip
                    zf.write(temp_path, certificate_filename)
        
        # Get the paper title from session
        paper_title = session.get('paper_title', 'Research_Paper')
        
        # Create a formatted filename
        download_name = get_file_download_name(f"{submission_id}_All_Reviews.zip", paper_title)
        
        # Prepare the zip file for download
        memory_file.seek(0)
        return send_file(
            memory_file,
            mimetype='application/zip',
            as_attachment=True,
            download_name=download_name
        )
        
    except Exception as e:
        print(f"Error creating review bundle: {str(e)}")
        traceback.print_exc()
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Log out from both the application and Auth0"""
    try:
        # Clear session data first
        session.clear()
        
        # Get the base URL from environment 
        base_url = os.getenv('AUTH0_BASE_URL')
        if not base_url:
            if 'DYNO' in os.environ:  # Heroku
                base_url = 'https://cuadrada-peer-review-e519e76bd103.herokuapp.com'
            else:
                base_url = request.url_root.rstrip('/')
            
        # Define Auth0 logout URL
        auth0_logout_url = f"https://{auth0_domain}/v2/logout"
        
        # Parameters for logout
        params = {
            'client_id': auth0_client_id,
            'returnTo': f"{base_url}/"
        }
        
        # Prepare and return the logout redirect
        logout_url = f"{auth0_logout_url}?{urlencode(params)}"
        return redirect(logout_url)
    except Exception as e:
        # Log the error
        print(f"Auth0 logout error: {str(e)}")
        traceback.print_exc()
        
        # Emergency fallback - just clear session and go to index
        session.clear()
        return redirect(url_for('index'))

@app.route('/thank-you')
def thank_you():
    """Show the thank you page after logout"""
    return render_template('logout.html')

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon"""
    # Since we're using an SVG favicon, return the SVG content directly
    svg_content = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect x='10' y='10' width='80' height='80' fill='none' stroke='purple' stroke-width='10'/></svg>"""
    return Response(svg_content, mimetype='image/svg+xml')

@app.route('/admin', methods=['GET'])
@admin_required
def admin_panel():
    """Admin panel for managing user subscriptions"""
    # Get all users and subscriptions
    users = get_all_users()
    subscriptions = get_all_subscriptions()
    
    # Create a map of user_id to subscription
    subscription_map = {sub['user_id']: sub for sub in subscriptions}
    
    # Combine user and subscription data
    user_data = []
    for user in users:
        user_id = user.get('user_id')
        subscription = subscription_map.get(user_id, {})
        user_data.append({
            'user_id': user_id,
            'email': user.get('email', ''),
            'name': user.get('name', ''),
            'created_at': user.get('created_at', ''),
            'plan_type': subscription.get('plan_type', 'none'),
            'status': subscription.get('status', ''),
            'max_reviews': subscription.get('max_reviews', 0),
            'current_period_start': subscription.get('current_period_start', ''),
            'current_period_end': subscription.get('current_period_end', '')
        })
    
    return render_template('admin.html', user_data=user_data)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        # If user is logged in, check if they're an admin
        if session.get('logged_in'):
            user_email = session.get('profile', {}).get('email', '')
            if user_email in ADMIN_EMAILS:
                return redirect(url_for('admin_verify'))
            else:
                flash('You do not have admin privileges.', 'error')
        else:
            # Redirect to regular login
            return redirect(url_for('login'))
    
    return render_template('admin_login.html')

@app.route('/admin/verify', methods=['GET', 'POST'])
def admin_verify():
    """Admin verification code page"""
    # Only allow access if user is logged in and has an admin email
    if not session.get('logged_in'):
        return redirect(url_for('admin_login'))
        
    user_email = session.get('profile', {}).get('email', '')
    if user_email not in ADMIN_EMAILS:
        return redirect(url_for('admin_login'))
    
    # Process verification code
    if request.method == 'POST':
        verification_code = request.form.get('code')
        # Get the ADMIN_CODE directly from env each time to ensure we have the latest value
        current_admin_code = os.getenv('ADMIN_CODE', '123456')
        print(f"Verification attempt with code: {verification_code}, expected: {current_admin_code}")
        
        # Ensure we're comparing strings
        if str(verification_code) == str(current_admin_code):
            session['is_admin'] = True
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid verification code.', 'error')
    
    return render_template('admin_verify.html')

@app.route('/admin/update_subscription', methods=['POST'])
@admin_required
def update_subscription_admin():
    """Update a user's subscription"""
    user_id = request.form.get('user_id')
    plan_type = request.form.get('plan_type')
    max_reviews = request.form.get('max_reviews')
    status = request.form.get('status', 'active')
    
    if not user_id or not plan_type or not max_reviews:
        flash('Missing required fields.', 'error')
        return redirect(url_for('admin_panel'))
    
    # Create subscription data
    subscription_data = {
        'plan_type': plan_type,
        'status': status,
        'max_reviews': int(max_reviews),
        'current_period_start': datetime.now().isoformat(),
        'current_period_end': (datetime.now() + timedelta(days=30)).isoformat()
    }
    
    # Update subscription
    if update_user_subscription(user_id, subscription_data):
        flash(f'Subscription updated for user {user_id}.', 'success')
    else:
        flash(f'Failed to update subscription for user {user_id}.', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/logout')
def admin_logout():
    """Logout from admin panel"""
    session.pop('is_admin', None)
    return redirect(url_for('admin_login'))

@app.route('/check_review_status/<submission_id>', methods=['GET'])
def check_review_status(submission_id):
    """Check the status of a review"""
    global review_results
    
    # Log the check attempt
    print(f"Checking review status for submission ID: '{submission_id}' | Type: {type(submission_id)}")
    
    # Ensure submission_id is a string
    submission_id = str(submission_id) if submission_id else None
    
    # Handle None or empty submission ID
    if not submission_id or submission_id == "None":
        print(f"Invalid submission ID in status check: '{submission_id}'")
        return jsonify({
            'status': 'error',
            'message': 'Invalid submission ID.'
        }), 400
    
    # CRITICAL FIX: First check our pickle file directly to see if we have completed results
    # This is more reliable than checking in-memory data that might be out of sync
    try:
        pickle_path = '/tmp/review_results.pickle'
        if os.path.exists(pickle_path):
            with open(pickle_path, 'rb') as f:
                pickled_results = pickle.load(f)
                if submission_id in pickled_results and pickled_results[submission_id].get('processing_complete', False):
                    print(f"Found completed results for '{submission_id}' in pickle file")
                    # Update in-memory results
                    review_results = pickled_results
                    return jsonify({
                        'status': 'complete',
                        'results': pickled_results[submission_id].get('results', {}),
                        'all_accepted': pickled_results[submission_id].get('all_accepted', False),
                        'has_accepted': pickled_results[submission_id].get('has_accepted', False),
                        'certificate_filename': pickled_results[submission_id].get('certificate_filename')
                    })
    except Exception as e:
        print(f"Error checking pickle file: {str(e)}")
        # Continue with normal flow if pickle check fails
    
    # Check if submission exists in our global results dictionary
    if submission_id not in review_results:
        print(f"Submission ID not found in review_results: '{submission_id}'")
        print(f"Available submission IDs: {list(review_results.keys())}")
        
        # Attempt to load the latest review results from disk
        try:
            loaded_results = load_review_results()
            if loaded_results and submission_id in loaded_results:
                review_results = loaded_results
                print(f"Loaded review_results from disk, found '{submission_id}'")
                result_data = review_results[submission_id]
                
                # If we found the submission and it's complete, return immediately
                if result_data.get('processing_complete', False):
                    print(f"Loaded data shows processing is complete for '{submission_id}'")
                    return jsonify({
                        'status': 'complete',
                        'results': result_data.get('results', {}),
                        'all_accepted': result_data.get('all_accepted', False),
                        'has_accepted': result_data.get('has_accepted', False),
                        'certificate_filename': result_data.get('certificate_filename')
                    })
        except Exception as e:
            print(f"Error loading review results from disk: {str(e)}")
        
        # If we have a file URL in the session, try to recover by initializing the review_results
        file_url = session.get('upload_file_url')
        if file_url:
            print(f"Attempting to recover submission data from session for polling. File URL: {file_url}")
            # Initialize review results for this submission from session data
            review_results[submission_id] = {
                'results': {},
                'all_accepted': False,
                'has_accepted': False,
                'processing_complete': False,
                'file_url': file_url
            }
            print(f"Created new entry in review_results for '{submission_id}' from session data")
            
            # Save the recovered data
            save_review_results()
        else:
            return jsonify({
                'status': 'not_found',
                'message': 'Review not found.'
            }), 404
    
    result_data = review_results[submission_id]
    
    # Deep check for processing_complete flag
    is_complete = result_data.get('processing_complete', False)
    
    # Also check if results are populated - this is a more reliable indicator
    has_results = bool(result_data.get('results')) and len(result_data.get('results', {})) >= 3
    
    # Log the status we're returning
    status = 'error' if 'error' in result_data else 'complete' if (is_complete or has_results) else 'processing'
    print(f"Status for submission '{submission_id}': {status}")
    
    if 'error' in result_data:
        return jsonify({
            'status': 'error',
            'message': result_data['error']
        }), 500
    
    if not (is_complete or has_results):
        return jsonify({
            'status': 'processing',
            'message': 'Review is still being processed.'
        })
    
    # Return the results if processing is complete
    return jsonify({
        'status': 'complete',
        'results': result_data.get('results', {}),
        'all_accepted': result_data.get('all_accepted', False),
        'has_accepted': result_data.get('has_accepted', False),
        'certificate_filename': result_data.get('certificate_filename')
    })

@app.route('/view_review_results/<submission_id>')
def view_review_results(submission_id):
    """View the results of a review"""
    global review_results
    
    try:
        print(f"Viewing review results for submission ID: '{submission_id}'")
        
        # Check login status - Fix for possible session structure
        if not session.get('logged_in'):
            print("User not logged in, redirecting to login")
            flash('You need to be logged in to view review results.')
            return redirect(url_for('login'))
        
        # Ensure submission_id is a string
        submission_id = str(submission_id) if submission_id else None
        
        # Handle None or empty submission ID
        if not submission_id or submission_id == "None":
            print(f"Invalid submission ID: '{submission_id}'")
            flash('Invalid submission ID. Please retry your submission.')
            return redirect(url_for('home'))
        
        # Store the submission ID in the session for use in other routes
        session['submission_id'] = submission_id
            
        # CRITICAL FIX: Check if we need to show the processing state
        # Determine processing state early to ensure consistent display
        is_processing = True  # Default to processing view
            
        # CRITICAL FIX: First check our pickle file directly to see if we have completed results
        # This ensures we're always using the most up-to-date data
        pickle_path = '/tmp/review_results.pickle'
        if os.path.exists(pickle_path):
            try:
                with open(pickle_path, 'rb') as f:
                    pickled_results = pickle.load(f)
                    if submission_id in pickled_results:
                        print(f"Found results for '{submission_id}' in pickle file")
                        # Update in-memory results
                        review_results = pickled_results
                        
                        # If complete, show results
                        result_data = pickled_results[submission_id]
                        if result_data.get('processing_complete', False) or (result_data.get('results') and len(result_data.get('results', {})) >= 3):
                            print(f"Pickle file shows processing is complete for '{submission_id}'")
                            # Processing is complete
                            is_processing = False
                            # Store review results in session for client-side access
                            session['review_results'] = result_data.get('results', {})
                            
                            return render_template(
                                'results.html',
                                results=result_data.get('results', {}),
                                all_accepted=result_data.get('all_accepted', False),
                                has_accepted=result_data.get('has_accepted', False),
                                certificate_filename=result_data.get('certificate_filename'),
                                submission_id=submission_id,
                                processing=is_processing  # Pass the correct processing state
                            )
            except Exception as e:
                print(f"Error reading pickle file: {str(e)}")
                # Continue with normal flow
        
        if submission_id not in review_results:
            print(f"Submission ID not found in review_results dictionary: '{submission_id}'")
            print(f"Available submission IDs: {list(review_results.keys())}")
            
            # Try to recover from session data
            file_url = session.get('upload_file_url')
            if file_url:
                print(f"Attempting to recover submission data from session. File URL: {file_url}")
                # Initialize review results for this submission from the URL
                review_results[submission_id] = {
                    'results': {},
                    'all_accepted': False,
                    'has_accepted': False,
                    'processing_complete': False,
                    'file_url': file_url
                }
                print(f"Created new entry in review_results for '{submission_id}' from session data")
                
                # Save the recovered data
                save_review_results()
                
                # If we had to create new entry, it's definitely still processing
                is_processing = True
            else:
                print(f"Could not recover submission data. No file URL in session.")
                flash('Review results not found. Please retry your submission.')
                return redirect(url_for('home'))
        
        result_data = review_results[submission_id]
        
        if 'error' in result_data:
            print(f"Error found for submission '{submission_id}': {result_data['error']}")
            flash(f"Error in processing your document: {result_data['error']}")
            return redirect(url_for('home'))
        
        # Check if processing is complete using multiple indicators
        is_complete = result_data.get('processing_complete', False)
        has_results = bool(result_data.get('results')) and len(result_data.get('results', {})) >= 3
        
        # Update the processing state based on our checks
        is_processing = not (is_complete or has_results)
        
        if is_processing:
            print(f"Processing not complete for submission '{submission_id}'")
            # Show processing page
            return render_template(
                'results.html',
                results={},
                submission_id=submission_id,
                processing=True  # Explicitly set processing to True
            )
        
        # If we reach here, processing is complete - make sure flag is set for future checks
        if not is_complete and has_results:
            result_data['processing_complete'] = True
            save_review_results()
            print(f"Updated processing_complete flag for '{submission_id}'")
        
        # If processing is complete, show the results
        print(f"Successfully retrieved results for submission '{submission_id}'")
        
        # Check if we need to generate a PDF certificate
        all_accepted = True
        for reviewer, review_data in result_data.get('results', {}).items():
            if review_data.get('decision') != 'ACCEPTED':
                all_accepted = False
                break
                
        if all_accepted and not result_data.get('certificate_filename'):
            try:
                print(f"Generating PDF certificate for submission '{submission_id}'")
                
                # Get paper title from session
                paper_title = session.get('paper_title', 'Research Paper')
                
                # Generate a PDF certificate
                certificate_filename = generate_certificate(paper_title, submission_id)
                result_data['certificate_filename'] = certificate_filename
                
                # Save to session for immediate access
                session['certificate_filename'] = certificate_filename
                
                # Save the updated review results with the certificate filename
                save_review_results()
                
                print(f"Generated certificate: {certificate_filename}")
            except Exception as e:
                print(f"Error generating certificate: {str(e)}")
                # Continue even if certificate generation fails
                flash('Warning: Unable to generate certificate. Please contact support.')
        
        # Store review results in session for client-side access
        session['review_results'] = result_data.get('results', {})
        
        return render_template(
            'results.html',
            results=result_data.get('results', {}),
            all_accepted=result_data.get('all_accepted', False),
            has_accepted=result_data.get('has_accepted', False),
            certificate_filename=result_data.get('certificate_filename'),
            submission_id=submission_id,
            processing=False  # Explicitly set processing to False when showing results
        )
    except Exception as e:
        error_message = f"Error viewing review results: {str(e)}"
        print(error_message)
        print(traceback.format_exc())
        flash(error_message)
        return redirect(url_for('home'))

@app.route('/debug/submissions', methods=['GET'])
def debug_submissions():
    """Debug route to view current submissions (admin only)"""
    # Only allow access to admin emails
    user_email = session.get('profile', {}).get('email', '')
    if user_email not in ADMIN_EMAILS:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get all submission IDs and their processing status
    submissions_data = {}
    for submission_id, data in review_results.items():
        submissions_data[submission_id] = {
            'processing_complete': data.get('processing_complete', False),
            'has_error': 'error' in data,
            'has_accepted': data.get('has_accepted', False),
            'needs_pdf_generation': data.get('needs_pdf_generation', False),
            'all_accepted': data.get('all_accepted', False),
            'reviewer_count': len(data.get('results', {}))
        }
    
    # Include session data to help with debugging
    session_data = {
        'submission_id': session.get('submission_id'),
        'paper_title': session.get('paper_title'),
        'logged_in': session.get('logged_in', False),
        'is_admin': session.get('is_admin', False),
        'user_email': user_email
    }
    
    return jsonify({
        'submissions': submissions_data,
        'session': session_data,
        'submission_count': len(submissions_data)
    })

@app.route('/api/process_status', methods=['GET'])
def process_status():
    """API endpoint to check the process status of the background workers"""
    try:
        # Only allow access to admins
        user_email = session.get('profile', {}).get('email', '')
        if user_email not in ADMIN_EMAILS:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Get task queue size
        queue_size = task_queue.qsize()
        
        # Get review results stats
        result_stats = {
            "total_submissions": len(review_results),
            "completed": sum(1 for data in review_results.values() if data.get('processing_complete', False)),
            "in_progress": sum(1 for data in review_results.values() if not data.get('processing_complete', False)),
            "with_errors": sum(1 for data in review_results.values() if 'error' in data),
            "needs_pdf_generation": sum(1 for data in review_results.values() if data.get('needs_pdf_generation', False))
        }
        
        return jsonify({
            "status": "ok",
            "queue_size": queue_size,
            "review_results": result_stats,
            "submissions": list(review_results.keys())
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle exceptions globally to prevent the app from crashing"""
    error_id = uuid.uuid4()
    error_message = f"Error ID: {error_id}, Type: {type(e).__name__}, Message: {str(e)}"
    
    # Log the full traceback with the error ID for tracking
    print(f"Exception occurred - {error_message}")
    traceback.print_exc()
    
    # For API endpoints, return JSON
    if request.path.startswith('/api/') or request.content_type == 'application/json':
        
        return jsonify({
            'error': 'An unexpected error occurred',
            'error_id': str(error_id),
            'details': str(e) if app.debug else 'Please contact support with this error ID'
        }), 500
    
    # Set a flash message if session is available
    try:
        if 'user' in session:
            flash('An unexpected error occurred. Our team has been notified.', 'error')
    except Exception:
        pass  # If session is broken, just continue
        
    # Redirect to index or an error page
    return redirect(url_for('index'))

@app.route('/certificate_download')
def certificate_download():
    """Simple route to generate and download certificate for the most recent submission"""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    try:
        # Get submission ID from session
        submission_id = session.get('submission_id')
        if not submission_id:
            flash('No active submission found.')
            return redirect(url_for('index'))
            
        # Check if we have results for this submission
        if submission_id not in review_results:
            # Try to load latest results
            loaded_results = load_review_results()
            if loaded_results:
                review_results.update(loaded_results)
                
            if submission_id not in review_results:
                flash('Review not found.')
                return redirect(url_for('index'))
        
        result_data = review_results[submission_id]
        
        # Force generation of certificate if all reviews are accepted
        all_accepted = True
        for reviewer, review_data in result_data.get('results', {}).items():
            if review_data.get('decision') != 'ACCEPTED':
                all_accepted = False
                break
        
        if not all_accepted:
            flash('Certificate is only available when all reviewers accept your paper.')
            return redirect(url_for('index'))
        
        # Get or generate certificate
        certificate_filename = result_data.get('certificate_filename')
        if not certificate_filename:
            # Get paper title
            paper_title = session.get('paper_title', 'Research Paper')
            
            # Generate certificate
            try:
                certificate_filename = generate_certificate(paper_title, submission_id)
                result_data['certificate_filename'] = certificate_filename
                session['certificate_filename'] = certificate_filename
                save_review_results()
            except Exception as e:
                print(f"Error generating certificate directly: {str(e)}")
                flash('Error generating certificate. Please contact support.')
                return redirect(url_for('index'))
        
        # Check if certificate file exists locally
        certificate_path = os.path.join(app.config['RESULTS_FOLDER'], certificate_filename)
        
        # If file doesn't exist locally, try to download or regenerate it
        if not os.path.exists(certificate_path):
            # Try to download from storage
            certificate_url = session.get('certificate_url')
            if certificate_url:
                try:
                    # Download to local path
                    response = requests.get(certificate_url)
                    if response.status_code == 200:
                        with open(certificate_path, 'wb') as f:
                            f.write(response.content)
                    else:
                        # If download fails, regenerate
                        paper_title = session.get('paper_title', 'Research Paper')
                        certificate_filename = generate_certificate(paper_title, submission_id)
                        certificate_path = os.path.join(app.config['RESULTS_FOLDER'], certificate_filename)
                except Exception as e:
                    # If error, regenerate
                    paper_title = session.get('paper_title', 'Research Paper')
                    certificate_filename = generate_certificate(paper_title, submission_id)
                    certificate_path = os.path.join(app.config['RESULTS_FOLDER'], certificate_filename)
            else:
                # No URL, regenerate
                paper_title = session.get('paper_title', 'Research Paper')
                certificate_filename = generate_certificate(paper_title, submission_id)
                certificate_path = os.path.join(app.config['RESULTS_FOLDER'], certificate_filename)
        
        # Create user-friendly filename
        paper_title = session.get('paper_title', 'Research_Paper')
        download_name = get_file_download_name(certificate_filename, paper_title)
        
        # Serve the file
        return send_file(
            certificate_path,
            as_attachment=True,
            download_name=download_name
        )
        
    except Exception as e:
        print(f"Error in direct certificate download: {str(e)}")
        traceback.print_exc()
        flash('Error downloading certificate. Please contact support.')
        return redirect(url_for('index'))

if __name__ == '__main__':
    # Get port from environment variable (for Heroku compatibility)
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
