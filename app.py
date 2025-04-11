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
    fix_upload_file_to_storage
)

load_dotenv()  # Load environment variables from .env file

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

# Increase session lifetime (default is 31 days)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

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

def allowed_file(filename):
    """Check if file has an allowed extension"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename():
    """Generate a unique filename with date prefix"""
    return f"{datetime.now().strftime('%Y%m%d')}_{str(uuid.uuid4())[:8]}"

def format_error_message(error_str):
    """Convert technical error messages to user-friendly ones"""
    if 'Review limit reached for your current plan' in error_str:
        return "You have reached the review limit for your current plan. Please upgrade your subscription to continue using our service."
    elif 'rate_limit_error' in error_str.lower() or 'rate limit' in error_str.lower():
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

def determine_paper_decision(review_text):
    """Analyze review text and return decision and summary"""
    # Check if it's a valid academic paper
    if not is_valid_academic_paper(review_text):
        return {
            "decision": "REJECTED",
            "summary": "REJECTED: The submitted document does not appear to be a proper academic paper. It lacks required academic structure and citations.",
            "accepted": False
        }
    
    # Determine decision based on content
    decision = "REJECTED"  # Default
    is_accepted = False
    
    if "FINAL DECISION: **ACCEPTED**" in review_text:
        decision = "ACCEPTED"
        is_accepted = True
    elif "FINAL DECISION: **ACCEPTED WITH MAJOR REVISION REQUIRED**" in review_text:
        decision = "REVISION"
        summary = "MAJOR REVISION REQUIRED: " + (review_text.split('\n\n')[0] if '\n\n' in review_text else review_text)
    elif "FINAL DECISION: **ACCEPTED WITH MINOR REVISION REQUIRED**" in review_text or "MINOR REVISIONS" in review_text.upper():
        decision = "REVISION"
        summary = "MINOR REVISION REQUIRED: " + (review_text.split('\n\n')[0] if '\n\n' in review_text else review_text)
    elif "ACCEPT" in review_text.upper() and not any(x in review_text.upper() for x in ["NOT ACCEPT", "MAJOR REVISION", "MINOR REVISION"]):
        decision = "ACCEPTED"
        is_accepted = True
    elif "REJECT" in review_text.upper() or "FINAL DECISION: **REJECTED**" in review_text:
        decision = "REJECTED"
    else:
        decision = "REVISION"
    
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
        "accepted": is_accepted
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
        
        # Generate the PDF with the review
        result_filename = generate_review_pdf(review_text, reviewer_name, submission_id)
        
        # Determine decision and get summary
        result = determine_paper_decision(review_text)
        
        # Add model information if downgraded
        model_info = ""
        if model_downgraded:
            model_info = f" [Note: Review generated using fallback model {final_model} due to rate limiting]"
        
        # Build result object
        return {
            'filename': result_filename,
            'decision': result['decision'],
            'summary': result['summary'] + (model_info if model_downgraded else ""),
            'full_review': result['full_review'] + (model_info if model_downgraded else ""),
            'accepted': result['accepted'],
            'model_used': final_model,
            'model_downgraded': model_downgraded
        }
    
    except Exception as e:
        print(f"Error in analysis with {reviewer_name}: {str(e)}")
        error_message = format_error_message(str(e))
        return {
            'filename': '',
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
            
            # Create default subscription
            subscription_data = {
                'user_id': user_id,
                'plan_type': 'free',
                'status': 'active',
                'max_reviews': 5,  # Default limit for free tier
                'current_period_start': datetime.now().isoformat(),
                'current_period_end': (datetime.now() + timedelta(days=30)).isoformat()
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

@app.route('/upload', methods=['POST'])
def upload_file():
    """Optimized upload handler that processes one reviewer at a time"""
    # Get user ID from session if available
    user_id = session.get('profile', {}).get('user_id', None)
    
    if not check_subscription_limit(user_id):
        return jsonify({
            'error': 'Review limit reached for your current plan. Please upgrade your subscription to continue.'
        }), 403
    
    if 'paper' not in request.files:
        return redirect(url_for('index'))
    
    file = request.files['paper']
    if file.filename == '' or not allowed_file(file.filename):
        return redirect(url_for('index'))
    
    try:
        submission_id = generate_unique_filename()
        filename = secure_filename(file.filename)
        
        # First save the file locally (this will be temporary)
        upload_path = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'], f"{submission_id}_{filename}")
        file.save(upload_path)
        
        # Upload to Supabase - using the fixed function
        file_url = fix_upload_file_to_storage(upload_path, 'uploads')
        
        # Store the file URL in the session
        if file_url:
            session['upload_file_url'] = file_url
        
        # Store the paper title in session for later use in download
        paper_title = request.form.get('paper_title', '')
        if paper_title:
            session['paper_title'] = paper_title
        else:
            # Use the filename as a fallback
            session['paper_title'] = os.path.splitext(filename)[0]
        
        # Process all three reviewers
        results = {}
        all_accepted = True
        
        # Process Reviewer 1 - start with default model (sonnet)
        agent = ClaudeAgent(model_index=1)  # Claude 3 Sonnet
        reviewer_name = "Reviewer 1"
        result = analyze_paper_with_agent(agent, upload_path, reviewer_name, submission_id)
        results[reviewer_name] = result
        all_accepted = all_accepted and result.get('accepted', False)
        
        # Process Reviewer 2 - also use default model
        agent = ClaudeAgent(model_index=1)  # Claude 3 Sonnet
        reviewer_name = "Reviewer 2"
        result = analyze_paper_with_agent(agent, upload_path, reviewer_name, submission_id)
        results[reviewer_name] = result
        all_accepted = all_accepted and result.get('accepted', False)
        
        # Process Reviewer 3 - also use default model
        agent = ClaudeAgent(model_index=1)  # Claude 3 Sonnet
        reviewer_name = "Reviewer 3"
        result = analyze_paper_with_agent(agent, upload_path, reviewer_name, submission_id)
        results[reviewer_name] = result
        all_accepted = all_accepted and result.get('accepted', False)
        
        # Store data to process other reviewers later if needed
        session['pending_file_path'] = upload_path
        session['submission_id'] = submission_id
        
        # Remove the 'accepted' key from each reviewer to save session space
        for reviewer, reviewer_result in results.items():
            if 'accepted' in reviewer_result:
                del reviewer_result['accepted']
            
        session['review_results'] = results
        session['all_accepted'] = all_accepted
        
        # Generate certificate if all reviewers accepted the paper
        certificate_filename = None
        if all_accepted:
            try:
                certificate_filename = generate_certificate(paper_title or filename, submission_id)
                session['certificate_filename'] = certificate_filename
            except Exception as e:
                print(f"Error generating certificate: {str(e)}")
                traceback.print_exc()
        
        # Log the review in the database
        if user_id:
            review_data = {
                'user_id': user_id,
                'submission_id': submission_id,
                'paper_title': paper_title or filename,
                'decision': 'PROCESSING',  # Will be updated later
                'created_at': datetime.now().isoformat(),
                'file_url': session.get('upload_file_url', '')
            }
            log_review(review_data)
            
        return render_template('results.html', 
                              results=results, 
                              all_accepted=all_accepted, 
                              submission_id=submission_id,
                              certificate_filename=certificate_filename,
                              processing=True)  # Flag to show processing status
            
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
        # Check for rate limiting errors
        if 'rate limit' in str(e).lower() or 'Review limit reached' in str(e):
            return jsonify({
                'error': format_error_message(str(e))
            }), 403
        
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

if __name__ == '__main__':
    # Get port from environment variable (for Heroku compatibility)
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
