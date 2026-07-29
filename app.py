from flask import Flask, render_template, request, redirect, url_for, session, jsonify, g
import sqlite3
import os
from datetime import timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_dev_only'
DATABASE = 'database.db'
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- Session Persistence Configuration ---
app.permanent_session_lifetime = timedelta(days=30)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Routes: Pages ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    
    role = session.get('role')
    if role == 'faculty':
        return render_template('admin.html', user=session)
    elif role == 'tpc_faculty':
        return render_template('tpc.html', user=session)
    elif role == 'forum_lead':
        return render_template('forum_lead.html', user=session)
    elif role == 'alumni':
        return render_template('alumni.html', user=session)
    elif role == 'student':
        return render_template('student.html', user=session)
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Routes: API ---

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role') # student, alumni, faculty, forum_lead, tpc_faculty
    admission_number = data.get('admission_number')
    phone_number = data.get('phone_number')
    year_start = data.get('year_start')
    year_end = data.get('year_end')
    forum_name = data.get('forum_name')
    branch = data.get('branch')
    position = data.get('position')
    
    if not name or not email or not password or not role:
        return jsonify({'error': 'Missing fields'}), 400

    hashed_pw = generate_password_hash(password)
    db = get_db()
    
    try:
        # Restriction: Only one Admin (faculty) and one TPC Faculty
        if role in ['faculty', 'tpc_faculty']:
            existing = db.execute('SELECT id FROM users WHERE role = ?', (role,)).fetchone()
            if existing:
                return jsonify({'error': f'A user with the role {role} already exists.'}), 409

        # Auto-approve students and faculty/tpc (for demo), Alumni and Forum Leads need approval
        is_approved = 1 if role in ['student', 'faculty', 'tpc_faculty'] else 0
        
        db.execute(
            'INSERT INTO users (name, email, password_hash, role, admission_number, is_approved, phone_number, year_start, year_end, forum_name, branch, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (name, email, hashed_pw, role, admission_number, is_approved, phone_number, year_start, year_end, forum_name, branch, position)
        )
        db.commit()
        return jsonify({'message': 'Registration successful'})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already exists'}), 409

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['name'] = user['name']
        session['role'] = user['role']
        session['is_approved'] = user['is_approved']
        session.permanent = True  # Make session last across browser restarts
        return jsonify({'role': user['role'], 'is_approved': user['is_approved']})
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/users/pending', methods=['GET'])
def get_pending_users():
    if session.get('role') != 'faculty':
        return jsonify({'error': 'Unauthorized'}), 403
    
    db = get_db()
    users = db.execute("SELECT id, name, email, admission_number, role, forum_name, branch, position FROM users WHERE is_approved = 0").fetchall()
    return jsonify([dict(row) for row in users])

@app.route('/api/users/approve', methods=['POST'])
def approve_user():
    if session.get('role') != 'faculty':
        return jsonify({'error': 'Unauthorized'}), 403
        
    user_id = request.json.get('user_id')
    db = get_db()
    db.execute('UPDATE users SET is_approved = 1 WHERE id = ?', (user_id,))
    db.commit()
    return jsonify({'message': 'User approved'})

@app.route('/api/users/reject', methods=['POST'])
def reject_user():
    if session.get('role') != 'faculty':
        return jsonify({'error': 'Unauthorized'}), 403
        
    user_id = request.json.get('user_id')
    db = get_db()
    db.execute('DELETE FROM users WHERE id = ? AND is_approved = 0', (user_id,))
    db.commit()
    return jsonify({'message': 'User rejected and removed'})

@app.route('/api/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    
    if request.method == 'GET':
        user = db.execute('SELECT name, email, admission_number, profession, company, tags, bio, phone_number, year_start, year_end, forum_name, branch, position FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        return jsonify(dict(user))
    
    else: # POST
        data = request.json
        db.execute('''
            UPDATE users 
            SET profession = ?, company = ?, tags = ?, bio = ?, phone_number = ?, year_start = ?, year_end = ?, forum_name = ?, branch = ?, position = ?
            WHERE id = ?
        ''', (data.get('profession'), data.get('company'), data.get('tags'), data.get('bio'), data.get('phone_number'), data.get('year_start'), data.get('year_end'), data.get('forum_name'), data.get('branch'), data.get('position'), session['user_id']))
        db.commit()
        return jsonify({'message': 'Profile updated'})

@app.route('/api/messages', methods=['GET', 'POST'])
def messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    
    if request.method == 'GET':
        query = '''
            SELECT m.*, u.name as sender_name, u.role as sender_role 
            FROM messages m 
            JOIN users u ON m.sender_id = u.id 
            ORDER BY created_at ASC
        '''
        msg_list = db.execute(query).fetchall()
        return jsonify([dict(row) for row in msg_list])
    
    else: # POST
        data = request.json
        content = data.get('content')
        if not content:
            return jsonify({'error': 'Empty message'}), 400
            
        # Add tags if forum lead
        user = db.execute('SELECT role, forum_name, branch, position FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user['role'] == 'forum_lead':
            tag = f" [{user['forum_name']} | {user['branch']} | {user['position']}]"
            content += tag

        db.execute('INSERT INTO messages (sender_id, content) VALUES (?, ?)', (session['user_id'], content))
        db.commit()
        return jsonify({'message': 'Message sent'})

@app.route('/api/messages/<int:message_id>', methods=['DELETE'])
def delete_message(message_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    message = db.execute('SELECT sender_id FROM messages WHERE id = ?', (message_id,)).fetchone()
    if not message:
        return jsonify({'error': 'Message not found'}), 404
        
    if session.get('role') == 'faculty' or message['sender_id'] == session['user_id']:
        db.execute('DELETE FROM messages WHERE id = ?', (message_id,))
        db.commit()
        return jsonify({'message': 'Message deleted'})
    
    return jsonify({'error': 'Forbidden'}), 403

@app.route('/api/posts', methods=['GET', 'POST'])
def posts():
    db = get_db()
    
    if request.method == 'GET':
        # Students see everything; Alumni see their own? For simplicity, fetch all public posts
        # Join with users to get author name
        query = '''
            SELECT p.*, u.name as author_name, u.role as author_role 
            FROM posts p 
            JOIN users u ON p.author_id = u.id 
            ORDER BY created_at DESC
        '''
        posts = db.execute(query).fetchall()
        return jsonify([dict(row) for row in posts])
        
    else: # POST
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        
        title = request.form.get('title')
        content = request.form.get('content')
        post_type = request.form.get('type') # announcement, achievement
        
        # Add tags if forum lead
        user = db.execute('SELECT role, forum_name, branch, position FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        if user['role'] == 'forum_lead':
            tag = f"\n\nForum: {user['forum_name']} | {user['branch']} | {user['position']}"
            content += tag

        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                import uuid
                filename = str(uuid.uuid4()) + "_" + file.filename
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_url = '/static/uploads/' + filename

        db.execute(
            'INSERT INTO posts (author_id, type, title, content, image_url) VALUES (?, ?, ?, ?, ?)',
            (session['user_id'], post_type, title, content, image_url)
        )
        db.commit()
        return jsonify({'message': 'Post created'})

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
def delete_post(post_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    db = get_db()
    post = db.execute('SELECT author_id FROM posts WHERE id = ?', (post_id,)).fetchone()
    if not post:
        return jsonify({'error': 'Post not found'}), 404
        
    if session.get('role') == 'faculty' or post['author_id'] == session['user_id']:
        db.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        db.commit()
        return jsonify({'message': 'Post deleted'})
    
    return jsonify({'error': 'Forbidden'}), 403

@app.route('/api/user/<int:user_id>/profile', methods=['GET'])
def get_user_full_profile(user_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
        
    db = get_db()
    user = db.execute('SELECT id, name, profession, company, tags, bio, year_start, year_end, forum_name, branch, position FROM users WHERE id = ?', (user_id,)).fetchone()
    if not user:
        return jsonify({'error': 'User not found'}), 404
        
    user_dict = dict(user)
    
    # Admin and TPC Faculty can see emails and phone numbers
    if session.get('role') in ['faculty', 'tpc_faculty']:
        extra = db.execute('SELECT email, phone_number FROM users WHERE id = ?', (user_id,)).fetchone()
        user_dict['email'] = extra['email']
        user_dict['phone_number'] = extra['phone_number']
        
    # Get all posts/announcements/achievements for this user
    posts = db.execute('''
        SELECT id, type, title, content, image_url, created_at 
        FROM posts 
        WHERE author_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,)).fetchall()
    
    user_dict['posts'] = [dict(p) for p in posts]
    
    return jsonify(user_dict)

@app.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('q', '').lower()
    
    db = get_db()
    sql = '''
        SELECT id, name, profession, company, tags, bio 
        FROM users 
        WHERE role = 'alumni' AND is_approved = 1 
        AND (
            lower(name) LIKE ? OR 
            lower(profession) LIKE ? OR 
            lower(company) LIKE ? OR 
            lower(tags) LIKE ? OR
            lower(bio) LIKE ?
        )
    '''
    term = f'%{query}%'
    results = db.execute(sql, (term, term, term, term, term)).fetchall()
    
    # Admin and TPC Faculty can see emails and phone numbers
    can_see_sensitive = session.get('role') in ['faculty', 'tpc_faculty']
    
    final_results = []
    for row in results:
        user_dict = dict(row)
        if can_see_sensitive:
            # We need to fetch email and phone as it wasn't in the original SQL
            user_info = db.execute('SELECT email, phone_number FROM users WHERE id = ?', (user_dict['id'],)).fetchone()
            user_dict['email'] = user_info['email']
            user_dict['phone_number'] = user_info['phone_number']
        final_results.append(user_dict)
        
    return jsonify(final_results)

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        import database
        database.init_db()
    # Run on 0.0.0.0 to be accessible on the local network (College Wi-Fi)
    app.run(debug=True, host='0.0.0.0', port=5000)
