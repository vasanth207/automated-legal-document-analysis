# app.py (Flask Backend)
from flask import Flask, request, jsonify, send_file, redirect, url_for, render_template
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
import re
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import docx
from pdfminer.high_level import extract_text as extract_text_from_pdf
from docx import Document
from collections import defaultdict
import math

# Create Flask app
app = Flask(__name__, template_folder='.', static_folder='static')
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Configure file upload
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'pdf', 'docx'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads directory if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# User Model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes for authentication
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    
    data = request.form
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400
        
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        login_user(user)
        return jsonify({"message": "Login successful"})
    
    return jsonify({"error": "Invalid username or password"}), 401

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    
    if request.method == 'POST':
        data = request.form
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not username or not email or not password:
            return jsonify({"error": "All fields are required"}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({"error": "Username already exists"}), 400
        
        if User.query.filter_by(email=email).first():
            return jsonify({"error": "Email already registered"}), 400
        
        user = User(username=username, email=email)
        user.set_password(password)
        
        try:
            db.session.add(user)
            db.session.commit()
            return jsonify({"message": "Registration successful"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": "Registration failed. Please try again."}), 500

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

# Document processing functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    return '\n'.join([paragraph.text for paragraph in doc.paragraphs])

def analyze_text(text):
    # Convert text to lowercase for easier matching
    text_lower = text.lower()
    
    # Define legal document indicators with stronger patterns
    legal_patterns = {
        'document_headers': [
            r'agreement', r'contract', r'memorandum', r'deed', r'certificate',
            r'affidavit', r'declaration', r'testimony', r'statute', r'regulation'
        ],
        'legal_phrases': [
            r'terms and conditions', r'hereby', r'pursuant to', r'hereinafter',
            r'witnesseth', r'in witness whereof', r'force majeure',
            r'governing law', r'jurisdiction', r'severability'
        ],
        'structural_elements': [
            r'article \d+', r'section \d+', r'clause \d+',
            r'appendix [a-z]', r'exhibit [a-z]', r'schedule [a-z]'
        ],
        'legal_terminology': [
            r'indemnification', r'liability', r'warranty', r'confidentiality',
            r'termination', r'arbitration', r'jurisdiction', r'compliance'
        ]
    }
    
    # Initialize scores for different aspects
    scores = {
        'header_score': 0,
        'phrase_score': 0,
        'structure_score': 0,
        'terminology_score': 0
    }
    
    # Check for document headers (30 points max)
    header_matches = sum(1 for pattern in legal_patterns['document_headers'] 
                        if re.search(rf'\b{pattern}\b', text_lower))
    scores['header_score'] = min(30, header_matches * 10)
    
    # Check for legal phrases (25 points max)
    phrase_matches = sum(1 for pattern in legal_patterns['legal_phrases'] 
                        if re.search(rf'\b{pattern}\b', text_lower))
    scores['phrase_score'] = min(25, phrase_matches * 5)
    
    # Check for structural elements (25 points max)
    structure_matches = sum(1 for pattern in legal_patterns['structural_elements'] 
                          if re.search(pattern, text_lower))
    scores['structure_score'] = min(25, structure_matches * 5)
    
    # Check for legal terminology (20 points max)
    terminology_matches = sum(1 for pattern in legal_patterns['legal_terminology'] 
                            if re.search(rf'\b{pattern}\b', text_lower))
    scores['terminology_score'] = min(20, terminology_matches * 4)
    
    # Calculate total confidence score (0-100)
    confidence_score = sum(scores.values())
    
    # Determine document status with detailed reasoning
    if confidence_score >= 70:
        status = "LEGAL"
        reason = "High confidence - Strong presence of legal elements"
    elif confidence_score >= 40:
        status = "POTENTIALLY LEGAL"
        reason = "Medium confidence - Some legal elements present"
    else:
        status = "NOT LEGAL"
        reason = "Low confidence - Few or no legal elements found"
    
    # Extract key phrases (sentences containing matched patterns)
    all_patterns = [pattern for patterns in legal_patterns.values() for pattern in patterns]
    sentences = [s.strip() for s in text.split('.') if s.strip()]
    key_phrases = []
    
    for sentence in sentences:
        if any(re.search(rf'\b{pattern}\b', sentence.lower()) for pattern in all_patterns):
            if len(sentence.split()) > 5:  # Ensure meaningful sentences only
                key_phrases.append(sentence)
    
    # Limit to top 5 most relevant phrases
    key_phrases = key_phrases[:5]
    
    return {
        "text_preview": text[:500],
        "document_status": status,
        "confidence_score": confidence_score,
        "reason": reason,
        "detailed_scores": scores,
        "key_phrases": key_phrases,
        "analysis_details": {
            "header_matches": header_matches,
            "phrase_matches": phrase_matches,
            "structure_matches": structure_matches,
            "terminology_matches": terminology_matches
        }
    }

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            # Extract text based on file type
            if filename.endswith('.pdf'):
                text = extract_text_from_pdf(file_path)
            elif filename.endswith('.docx'):
                text = extract_text_from_docx(file_path)
            else:
                return jsonify({"error": "Unsupported file type"}), 400

            # Analyze the extracted text
            analysis_result = analyze_text(text)

            # Clean up the uploaded file
            os.remove(file_path)

            return jsonify({
                "text": analysis_result["text_preview"],
                "analysis": {
                    "document_status": analysis_result["document_status"],
                    "confidence_score": analysis_result["confidence_score"],
                    "reason": analysis_result["reason"],
                    "detailed_scores": analysis_result["detailed_scores"],
                    "key_phrases": analysis_result["key_phrases"],
                    "analysis_details": analysis_result["analysis_details"]
       }
            })
        except Exception as e:
            # Clean up the file in case of error
            if os.path.exists(file_path):
                os.remove(file_path)
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Invalid file extension"}), 400

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create database tables
    app.run(debug=True)
