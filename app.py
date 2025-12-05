import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash
from werkzeug.utils import secure_filename
from functools import wraps

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# --- Folders & Limits ---
DROP_FOLDER = 'drops'
DATABASE_FILE = 'database.txt'
USERS_FILE = 'users.txt'
CLOUD_FOLDER = 'cloud'
NOTES_FOLDER = 'notes'
ALLOWED_EXTENSIONS = {'txt','md','jpg','jpeg','png'}
MAX_STORAGE_PER_USER = 2 * 1024 * 1024 * 1024  # 2GB

# --- Helpers ---
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE,'r',encoding='utf-8') as f:
        return {line.split(':')[0].strip(): line.split(':')[1].strip() for line in f if ':' in line}

def save_users(users_dict):
    with open(USERS_FILE,'w',encoding='utf-8') as f:
        for u,p in users_dict.items():
            f.write(f"{u}:{p}\n")

def load_database():
    if not os.path.exists(DATABASE_FILE):
        return []
    with open(DATABASE_FILE,'r',encoding='utf-8') as f:
        return [line.strip() for line in f]

def get_user_cloud_folder(username):
    path = os.path.join(CLOUD_FOLDER, username)
    os.makedirs(path, exist_ok=True)
    return path

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def get_hosted_file_path(username):
    folder = get_user_cloud_folder(username)
    path = os.path.join(folder, 'hosted.json')
    if not os.path.exists(path):
        with open(path,'w') as f:
            json.dump({},f)
    return path

def load_hosted(username):
    path = get_hosted_file_path(username)
    with open(path,'r') as f:
        return json.load(f)

def save_hosted(username,data):
    path = get_hosted_file_path(username)
    with open(path,'w') as f:
        json.dump(data,f)

def get_user_notes_file(username):
    os.makedirs(NOTES_FOLDER, exist_ok=True)
    return os.path.join(NOTES_FOLDER,f"{username}.txt")

# --- ROUTES ---

# LOGIN / LOGOUT
@app.route('/', methods=['GET','POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('home'))
    message = ''
    if request.method=='POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','').strip()
        users = load_users()
        if username in users and users[username]==password:
            session['logged_in'] = True
            session['username'] = username
            session['theme'] = 'light'
            return redirect(url_for('home'))
        else:
            message = 'Invalid username or password.'
    return render_template('login.html', message=message)

@app.route('/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('login'))

# HOME DASHBOARD
@app.route('/home')
@login_required
def home():
    info = f"Welcome, {session['username']}!"
    return render_template('home.html', info=info, theme=session.get('theme','light'))

# LOOKUP
@app.route('/lookup', methods=['GET','POST'])
@login_required
def lookup():
    message = ''
    if request.method=='POST':
        search_input = request.form.get('searchInput','').strip()
        if not search_input:
            message = 'Enter a Discord ID or username.'
        else:
            database = load_database()
            match = next((line for line in database if search_input in line), None)
            if match:
                message = f'Found: {match}'
            else:
                message = f'No results for "{search_input}".'
    return render_template('lookup.html', message=message, theme=session.get('theme','light'))

# FILE DROPS
@app.route('/drops')
@login_required
def drops():
    os.makedirs(DROP_FOLDER, exist_ok=True)
    files = os.listdir(DROP_FOLDER)
    return render_template('drops.html', files=files, theme=session.get('theme','light'))

@app.route('/drops/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(DROP_FOLDER, filename, as_attachment=True)

# SETTINGS
@app.route('/settings', methods=['GET','POST'])
@login_required
def settings():
    message = ''
    if request.method=='POST':
        users = load_users()
        # Change password
        current = request.form.get('current_password','').strip()
        new = request.form.get('new_password','').strip()
        confirm = request.form.get('confirm_password','').strip()
        if current and new and confirm:
            username = session['username']
            if users.get(username)==current:
                if new==confirm:
                    users[username]=new
                    save_users(users)
                    message = 'Password changed successfully.'
                else:
                    message = 'New passwords do not match.'
            else:
                message = 'Current password incorrect.'
        # Change theme
        theme = request.form.get('theme')
        if theme in ['light','dark']:
            session['theme'] = theme
            message += ' Theme changed.'
    return render_template('settings.html', message=message, theme=session.get('theme','light'))

# --- NOTES ---
@app.route('/notes', methods=['GET','POST'])
@login_required
def notes():
    username = session['username']
    notes_file = get_user_notes_file(username)
    content = ''
    if os.path.exists(notes_file):
        with open(notes_file,'r',encoding='utf-8') as f:
            content = f.read()
    if request.method=='POST':
        content = request.form.get('notes','')
        with open(notes_file,'w',encoding='utf-8') as f:
            f.write(content)
        flash('Notes saved.')
    return render_template('notes.html', notes=content, theme=session.get('theme','light'))

# --- CLOUD ---
@app.route('/cloud', methods=['GET','POST'])
@login_required
def cloud():
    username = session['username']
    folder = get_user_cloud_folder(username)
    os.makedirs(folder, exist_ok=True)
    files = [f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder,f)) and f!='hosted.json']
    hosted = load_hosted(username)

    # Upload
    if request.method=='POST':
        if 'file' not in request.files:
            flash('No file selected.')
        else:
            file = request.files['file']
            if file.filename=='':
                flash('No file selected.')
            elif allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(folder, filename)
                total_size = sum(os.path.getsize(os.path.join(folder,f)) for f in files)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if total_size + file_size > MAX_STORAGE_PER_USER:
                    flash('Limit of 2GB reached.')
                else:
                    file.save(filepath)
                    flash(f'{filename} uploaded!')
            else:
                flash('Only JPG, PNG, JPEG and TXT files are allowed.')
        return redirect(url_for('cloud'))

    return render_template('cloud.html', files=files, hosted=hosted, theme=session.get('theme','light'))

@app.route('/cloud/download/<filename>')
@login_required
def download_cloud(filename):
    username = session['username']
    folder = get_user_cloud_folder(username)
    return send_from_directory(folder, filename, as_attachment=True)

@app.route('/cloud/host/<filename>')
@login_required
def host_file(filename):
    username = session['username']
    hosted = load_hosted(username)
    hosted[filename]=True
    save_hosted(username, hosted)
    flash(f'{filename} is now hosted!')
    return redirect(url_for('cloud'))

@app.route('/cloud/unhost/<filename>')
@login_required
def unhost_file(filename):
    username = session['username']
    hosted = load_hosted(username)
    if filename in hosted:
        hosted[filename]=False
        save_hosted(username, hosted)
        flash(f'{filename} is no longer hosted.')
    return redirect(url_for('cloud'))

@app.route('/cloud/delete/<filename>')
@login_required
def delete_cloud(filename):
    username = session['username']
    folder = get_user_cloud_folder(username)
    filepath = os.path.join(folder, filename)
    hosted = load_hosted(username)

    if os.path.exists(filepath):
        os.remove(filepath)
        if filename in hosted:
            hosted.pop(filename)
            save_hosted(username, hosted)
        flash(f'{filename} deleted.')
    else:
        flash(f'{filename} does not exist.')
    return redirect(url_for('cloud'))

# Public Image Host link
@app.route('/host/<username>/<filename>')
def public_host(username, filename):
    hosted = load_hosted(username)
    if hosted.get(filename):
        folder = get_user_cloud_folder(username)
        return send_from_directory(folder, filename)
    return "File not available", 404

# --- MAIN ---
if __name__ == '__main__':
    os.makedirs(DROP_FOLDER, exist_ok=True)
    os.makedirs(CLOUD_FOLDER, exist_ok=True)
    os.makedirs(NOTES_FOLDER, exist_ok=True)
    app.run(debug=True)
