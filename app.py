from flask import Flask, render_template, request, send_file, url_for, redirect, jsonify, session, flash
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
from pymongo import MongoClient
import stripe
import zipfile
import io
import traceback
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
import requests
import time

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
app.secret_key = os.urandom(24)  # or use a fixed secret key for production

# Auth0 setup
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=auth0_client_id,
    client_secret=auth0_client_secret,
    api_base_url=f'https://{auth0_domain}',
    access_token_url=f'https://{auth0_domain}/oauth/token',
    authorize_url=f'https://{auth0_domain}/authorize',
    client_kwargs={
        'scope': 'openid profile email',
        'audience': f'https://{auth0_domain}/api/v2/',
        'verify_ssl': False,  # Only for local development
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

# MongoDB setup with retry logic
def get_mongo_client():
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            client = MongoClient(mongodb_uri, 
                                connectTimeoutMS=30000, 
                                socketTimeoutMS=None, 
                                socketKeepAlive=True, 
                                serverSelectionTimeoutMS=30000)
            # Quick check that connection works
            client.admin.command('ping')
            return client
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"MongoDB connection attempt {attempt+1} failed: {str(e)}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                print(f"Failed to connect to MongoDB after {max_retries} attempts: {str(e)}")
                # Return a placeholder client - operations will fail but app will still load
                return MongoClient(mongodb_uri)

client = get_mongo_client()
db = client.cuadrada
users = db.users
subscriptions = db.subscriptions

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
    if 'rate_limit_error' in error_str:
        return "Our review system is currently busy. Please wait 60 seconds and try again."
    elif 'authentication_error' in error_str or 'invalid x-api-key' in error_str:
        return "There was an issue with our review system. Please contact support."
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
            return certificate_filename
            
        except Exception as e:
            print(f"Error formatting certificate content: {str(e)}")
            raise
            
    except Exception as e:
        print(f"Error generating certificate: {str(e)}")
        return None

def generate_review_pdf(review_text, reviewer_name, submission_id):
    """Generate a properly formatted PDF review with Cuadrada branding"""
    # Remove spaces from reviewer name for the filename
    reviewer_name_filename = reviewer_name.replace(' ', '')
    result_filename = f"{submission_id}_{reviewer_name_filename}_Analysis.pdf"
    result_path = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'], result_filename)
    
    c = canvas.Canvas(result_path, pagesize=letter)
    width, height = letter

    # Add header with Cuadrada branding
    c.setFillColorRGB(0.5, 0, 0.5)  # Purple color
    c.setFont("Helvetica-Bold", 24)
    c.drawString(72, height - 72, "Cuadrada")
    
    c.setFont("Helvetica", 14)
    c.drawString(72, height - 95, "AI-Powered Peer Review")
    
    # Add reviewer info
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 140, reviewer_name)  # Use original reviewer name with spaces for display
    
    # Add date and ID
    c.setFont("Helvetica", 10)
    current_date = datetime.now().strftime("%B %d, %Y")
    c.drawString(72, height - 160, f"Review Date: {current_date}")
    c.drawString(72, height - 175, f"Submission ID: {submission_id}")
    
    # Add decorative line
    c.setStrokeColorRGB(0.5, 0, 0.5)
    c.setLineWidth(2)
    c.line(72, height - 190, width - 72, height - 190)

    # Format and add review text
    c.setFont("Helvetica", 12)
    text_object = c.beginText()
    text_object.setTextOrigin(72, height - 220)
    
    # Word wrap the review text
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
    
    return result_filename

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
        review_text = agent.analyze_paper(filepath)
        if not review_text:
            raise ValueError(f"No review text generated by {reviewer_name}")
        
        # Generate the PDF with the review
        result_filename = generate_review_pdf(review_text, reviewer_name, submission_id)
        
        # Determine decision and get summary
        result = determine_paper_decision(review_text)
        
        # Build result object
        return {
            'filename': result_filename,
            'decision': result['decision'],
            'summary': result['summary'],
            'full_review': result['full_review'],
            'accepted': result['accepted']
        }
    
    except Exception as e:
        print(f"Error in analysis with {reviewer_name}: {str(e)}")
        error_message = format_error_message(str(e))
        return {
            'filename': '',
            'decision': 'ERROR',
            'summary': error_message,
            'full_review': error_message,
            'accepted': False
        }

def check_subscription_limit():
    """Check if user has remaining reviews in their plan"""
    return True  # Always allow reviews, no subscription check

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
    return auth0.authorize_redirect(
        redirect_uri=auth0_callback_url,
        audience=f'https://{auth0_domain}/api/v2/'
    )

@app.route('/callback')
def callback():
    """Auth0 callback handler"""
    try:
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
        
        return redirect(url_for('index'))
        
    except Exception as e:
        print(f"Auth0 login error: {str(e)}")
        return redirect(url_for('auth_error'))

@app.route('/auth-error')
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
    if not check_subscription_limit():
        return jsonify({
            'error': 'Review limit reached for your current plan'
        }), 403
    
    if 'paper' not in request.files:
        return redirect(url_for('index'))
    
    file = request.files['paper']
    if file.filename == '' or not allowed_file(file.filename):
        return redirect(url_for('index'))
    
    try:
        submission_id = generate_unique_filename()
        filename = secure_filename(file.filename)
        upload_path = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'], f"{submission_id}_{filename}")
        file.save(upload_path)
        
        # Store the paper title in session for later use in download
        paper_title = request.form.get('paper_title', '')
        if paper_title:
            session['paper_title'] = paper_title
        else:
            # Use the filename as a fallback
            session['paper_title'] = os.path.splitext(filename)[0]
        
        # Create agents
        agents = {
            'Reviewer 1': ClaudeAgent(),
            'Reviewer 2': ClaudeAgent(),
            'Reviewer 3': ClaudeAgent()
        }
        
        # Analyze with each agent
        results = {}
        all_accepted = True
        
        for agent_name, agent in agents.items():
            result = analyze_paper_with_agent(agent, upload_path, agent_name, submission_id)
            results[agent_name] = result
            
            # Update all_accepted flag
            if not result.get('accepted', False):
                all_accepted = False
        
        # Store minimal data in session to avoid size limit
        # Remove the 'accepted' key from each result since we have all_accepted
        for key in results:
            if 'accepted' in results[key]:
                del results[key]['accepted']
                
        session['review_results'] = results
        session['submission_id'] = submission_id
        session['all_accepted'] = all_accepted
        
        # Generate certificate if all reviewers accepted
        if all_accepted:
            try:
                certificate_filename = generate_certificate(paper_title or filename, submission_id)
                session['certificate_filename'] = certificate_filename
            except Exception as e:
                print(f"Error generating certificate: {str(e)}")
                session['certificate_filename'] = None
            
        return render_template('results.html', 
                              results=results, 
                              all_accepted=all_accepted, 
                              submission_id=submission_id,
                              certificate_filename=session.get('certificate_filename'))
            
    except Exception as e:
        print(f"Error processing file: {str(e)}")
        traceback.print_exc()  # Print the full traceback for debugging
        return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    """Handle file downloads with proper error checking"""
    # Get the results folder path
    results_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
    
    # Find the file using helper function
    file_path = find_file_with_secure_path(results_dir, filename)
    if not file_path:
        return redirect(url_for('index'))
    
    # Extract paper title from session if available
    paper_title = session.get('paper_title', 'Report')
    
    # Create a formatted filename
    download_name = get_file_download_name(filename, paper_title)
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=download_name
        )
    except Exception as e:
        print(f"Error downloading file: {str(e)}")
        return redirect(url_for('index'))

@app.route('/download_certificate')
def download_certificate():
    try:
        # Get the most recent certificate file from the results folder
        results_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
        
        # If we have a certificate filename in session, use that
        if 'certificate_filename' in session and session['certificate_filename']:
            certificate_path = os.path.join(results_dir, session['certificate_filename'])
            if os.path.exists(certificate_path):
                paper_title = session.get('paper_title', 'Research_Paper')
                download_name = get_file_download_name(session['certificate_filename'], paper_title)
                return send_file(
                    certificate_path,
                    as_attachment=True,
                    download_name=download_name
                )
        
        # Fallback: get the most recent certificate
        certificate_files = [f for f in os.listdir(results_dir) if f.endswith('_certificate.pdf')]
        if not certificate_files:
            return redirect(url_for('index'))
            
        latest_certificate = sorted(certificate_files)[-1]
        certificate_path = os.path.join(results_dir, latest_certificate)
        
        if os.path.exists(certificate_path):
            paper_title = session.get('paper_title', 'Research_Paper')
            download_name = get_file_download_name(latest_certificate, paper_title)
            
            return send_file(
                certificate_path,
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
        # Find the original file
        uploads_dir = os.path.join(os.path.dirname(__file__), app.config['UPLOAD_FOLDER'])
        files = [f for f in os.listdir(uploads_dir) 
                if f.startswith(submission_id)]
        if not files:
            return jsonify({'success': False, 'error': 'Original file not found'})
            
        upload_path = os.path.join(uploads_dir, files[0])
        
        # Create new agent and analyze
        agent = ClaudeAgent()
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
        # Get all files related to this submission
        results_dir = os.path.join(os.path.dirname(__file__), app.config['RESULTS_FOLDER'])
        all_files = [f for f in os.listdir(results_dir) 
                    if f.startswith(submission_id) and f.endswith('.pdf')]
        
        if not all_files:
            print(f"No files found for submission: {submission_id}")
            return redirect(url_for('index'))
            
        # Create a zip file in memory
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for file in all_files:
                file_path = os.path.join(results_dir, file)
                zf.write(file_path, file)
        
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
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Log out from both the application and Auth0"""
    # Clear session data
    session.clear()
    
    # Redirect to Auth0 logout endpoint
    params = {
        'returnTo': url_for('thank_you', _external=True),
        'client_id': auth0_client_id
    }
    return redirect(auth0.api_base_url + '/v2/logout?' + urlencode(params))

@app.route('/thank-you')
def thank_you():
    """Show the thank you page after logout"""
    return render_template('logout.html')

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle exceptions globally to prevent the app from crashing"""
    error_id = uuid.uuid4()
    error_message = f"Error ID: {error_id}, Type: {type(e).__name__}, Message: {str(e)}"
    
    # Log the full traceback with the error ID for tracking
    print(f"Exception occurred - {error_message}")
    traceback.print_exc()
    
    # For API endpoints, return JSON
    if request.path.startswith('/api/'):
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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
