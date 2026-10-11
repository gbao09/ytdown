from flask import Flask, render_template, request, jsonify, session, url_for
import yt_dlp
import os
import urllib.parse as urlparse
import sqlite3
import hashlib
from datetime import datetime, timedelta
import shutil
from werkzeug.utils import secure_filename
import librosa
import numpy as np
import subprocess

app = Flask(__name__)
app.secret_key = "cyber_studio_secret_key"

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

STEMS_OUTPUT_FOLDER = os.path.join(os.getcwd(), 'static', 'stems_output')
if not os.path.exists(STEMS_OUTPUT_FOLDER):
    os.makedirs(STEMS_OUTPUT_FOLDER)

DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'Cyber_Downloads_Music')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            avatar TEXT,
            is_admin INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            title TEXT,
            format TEXT,
            path TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_user_avatar(username):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT avatar FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        return row[0]
    return 'default_avatar.png'

def check_is_admin(username):
    if not username:
        return False
    if username.lower() == 'admin':
        return True
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT is_admin FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()
    return row and row[0] == 1

def get_drive_space(path):
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        return {
            "drive": "Cloud Storage",
            "free": f"{free / (2**30):.1f} GB",
            "total": f"{total / (2**30):.1f} GB"
        }
    except Exception:
        return {"drive": "Cloud", "free": "50 GB", "total": "100 GB"}

@app.route('/')
def index():
    if 'user' in session:
        space_info = get_drive_space(DOWNLOAD_FOLDER)
        avatar = get_user_avatar(session['user'])
        is_admin = check_is_admin(session['user'])
        return render_template('index.html', logged_in=True, user=session['user'], avatar=avatar, path=DOWNLOAD_FOLDER, space=space_info, is_admin=is_admin)
    return render_template('index.html', logged_in=False)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    remember = data.get('remember', True)

    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Vui lòng nhập đầy đủ thông tin!'})

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == hash_password(password):
        session['user'] = username
        if remember:
            session.permanent = True
            app.permanent_session_lifetime = timedelta(weeks=1)
        return jsonify({'status': 'success'})
    else:
        return jsonify({'status': 'error', 'message': 'Sai tài khoản hoặc mật khẩu!'})

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Vui lòng nhập thông tin đăng ký!'})

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
    admin_exists = cursor.fetchone()[0] > 0

    is_admin_val = 1 if (username.lower() == 'admin' and not admin_exists) else 0

    try:
        cursor.execute("INSERT INTO users (username, password, avatar, is_admin) VALUES (?, ?, ?, ?)", 
                       (username, hash_password(password), 'default_avatar.png', is_admin_val))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Đăng ký thành công! Hãy đăng nhập.'})
    except sqlite3.IntegrityError:
        return jsonify({'status': 'error', 'message': 'Tên đăng nhập đã tồn tại!'})
    finally:
        conn.close()

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Chưa đăng nhập!'})
    
    if 'avatar' not in request.files:
        return jsonify({'status': 'error', 'message': 'Không tìm thấy file ảnh!'})
    
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'Chưa chọn file ảnh!'})
    
    if file:
        filename = f"{session['user']}_{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET avatar=? WHERE username=?", (filename, session['user']))
        conn.commit()
        conn.close()

        return jsonify({'status': 'success', 'avatar': filename})
    
    return jsonify({'status': 'error', 'message': 'Lỗi tải lên ảnh!'})

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user', None)
    return jsonify({'status': 'success'})

@app.route('/browse', methods=['POST'])
def browse():
    space_info = get_drive_space(DOWNLOAD_FOLDER)
    return jsonify({'status': 'success', 'path': DOWNLOAD_FOLDER, 'space': space_info})

@app.route('/search_yt', methods=['POST'])
def search_yt():
    data = request.get_json()
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'status': 'error', 'results': []})
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
    }
    results = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(f"ytsearch8:{query}", download=False)
            if 'entries' in search_results:
                entries = search_results['entries']
                
                artist_name = query.title()
                channel_url = f"https://www.youtube.com/@{query.replace(' ', '')}"
                
                channel_thumb = "https://www.youtube.com/s/desktop/f52e5052/img/favicon_144x144.png"
                for e in entries:
                    if e.get('thumbnail'):
                        channel_thumb = e.get('thumbnail')
                        break
                    elif e.get('thumbnails') and len(e['thumbnails']) > 0:
                        channel_thumb = e['thumbnails'][-1].get('url')
                        break

                for e in entries:
                    up = e.get('uploader') or e.get('channel')
                    if up and query.lower() in up.lower():
                        artist_name = up
                        break
                
                results.append({
                    'id': 'channel_main',
                    'title': artist_name,
                    'uploader': artist_name,
                    'duration': '',
                    'thumbnail': channel_thumb,
                    'url': channel_url,
                    'is_channel': True
                })

                for entry in entries:
                    vid_id = entry.get('id')
                    title = entry.get('title') or 'Unknown Track'
                    uploader = entry.get('uploader') or entry.get('channel') or 'YouTube Creator'
                    
                    thumbnail = entry.get('thumbnail')
                    if entry.get('thumbnails') and len(entry['thumbnails']) > 0:
                        thumbnail = entry['thumbnails'][-1].get('url')
                    if not thumbnail and vid_id:
                        thumbnail = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

                    duration_str = ""
                    duration_sec = entry.get('duration')
                    if duration_sec:
                        m, s = divmod(int(duration_sec), 60)
                        duration_str = f"{m}:{s:02d}"

                    results.append({
                        'id': vid_id,
                        'title': title,
                        'uploader': uploader,
                        'duration': duration_str,
                        'thumbnail': thumbnail,
                        'url': f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "#",
                        'is_channel': False
                    })
        return jsonify({'status': 'success', 'results': results})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'results': []})

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    raw_url = data.get('url', '').strip()

    if not raw_url:
        return jsonify({'status': 'error', 'message': 'Đường dẫn YouTube không được để trống!'})

    parsed_url = urlparse.urlparse(raw_url)
    if "youtu.be" in parsed_url.netloc:
        clean_url = f"https://www.youtube.com/watch?v={parsed_url.path.lstrip('/')}"
    else:
        query_params = urlparse.parse_qs(parsed_url.query)
        clean_url = f"https://www.youtube.com/watch?v={query_params['v'][0]}" if "v" in query_params else raw_url

    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=True)
            title = info.get('title', 'Unknown Audio')
            filename = f"{title}.wav"

        if 'user' in session:
            conn = sqlite3.connect("users.db")
            cursor = conn.cursor()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("INSERT INTO history (username, title, format, path, timestamp) VALUES (?, ?, ?, ?, ?)",
                           (session['user'], title, 'WAV', DOWNLOAD_FOLDER, timestamp))
            conn.commit()
            conn.close()

        space_info = get_drive_space(DOWNLOAD_FOLDER)
        return jsonify({'status': 'success', 'path': DOWNLOAD_FOLDER, 'filename': filename, 'space': space_info})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)[:120]})

@app.route('/analyze_audio', methods=['POST'])
def analyze_audio():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Chưa đăng nhập!'})
    
    if 'audio' not in request.files:
        return jsonify({'status': 'error', 'message': 'Không tìm thấy tệp âm thanh!'})
    
    file = request.files['audio']
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'Chưa chọn tệp âm thanh!'})
    
    try:
        temp_path = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
        file.save(temp_path)
        
        y, sr = librosa.load(temp_path, duration=60)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = round(float(np.atleast_1d(tempo)[0]), 1)
        
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = np.mean(chroma, axis=1)
        
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
        minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
        
        best_key = ""
        max_corr = -1
        is_major = True
        
        for i in range(12):
            maj_rot = np.roll(major_profile, i)
            min_rot = np.roll(minor_profile, i)
            
            corr_maj = np.corrcoef(chroma_mean, maj_rot)[0, 1]
            corr_min = np.corrcoef(chroma_mean, min_rot)[0, 1]
            
            if corr_maj > max_corr:
                max_corr = corr_maj
                best_key = keys[i]
                is_major = True
            if corr_min > max_corr:
                max_corr = corr_min
                best_key = keys[i]
                is_major = False
                
        key_result = f"{best_key} {'Major (Trưởng)' if is_major else 'Minor (Thứ)'}"
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        return jsonify({'status': 'success', 'bpm': bpm, 'key': key_result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/separate_audio', methods=['POST'])
def separate_audio():
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Chưa đăng nhập!'})
    
    if 'audio' not in request.files:
        return jsonify({'status': 'error', 'message': 'Không tìm thấy tệp âm thanh!'})
    
    file = request.files['audio']
    model_type = request.form.get('model', '2stems')
    
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'Chưa chọn tệp âm thanh!'})
    
    try:
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        file.save(file_path)
        
        stems_count = "4" if model_type == '4stems' else "2"
        cmd = f"demucs -n htdemucs --two-stems=vocals -d cpu \"{file_path}\" -o \"{STEMS_OUTPUT_FOLDER}\""
        if stems_count == "4":
            cmd = f"demucs -n htdemucs -d cpu \"{file_path}\" -o \"{STEMS_OUTPUT_FOLDER}\""
            
        subprocess.run(cmd, shell=True, check=True)
        
        base_name = os.path.splitext(filename)[0]
        result_subfolder = os.path.join(STEMS_OUTPUT_FOLDER, 'htdemucs', base_name)
        
        stems_result = []
        if os.path.exists(result_subfolder):
            for stem_file in os.listdir(result_subfolder):
                if stem_file.endswith('.wav') or stem_file.endswith('.mp3'):
                    display_name = stem_file.replace('.wav', '').replace('.mp3', '').title()
                    stems_result.append({
                        'name': display_name,
                        'url': f'/static/stems_output/htdemucs/{base_name}/{stem_file}'
                    })

        if os.path.exists(file_path):
            os.remove(file_path)

        return jsonify({
            'status': 'success',
            'message': 'Tách Stems AI thành công!',
            'stems': stems_result
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_admin_data', methods=['GET'])
def get_admin_data():
    if 'user' not in session or not check_is_admin(session['user']):
        return jsonify({'status': 'error', 'message': 'Unauthorized'})
    
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, title, format, path, timestamp FROM history ORDER BY id DESC")
    history_rows = cursor.fetchall()
    history_list = [{'user': r[0], 'title': r[1], 'format': r[2], 'path': r[3], 'time': r[4]} for r in history_rows]

    cursor.execute("SELECT username, is_admin FROM users")
    user_rows = cursor.fetchall()
    users_list = [{'username': r[0], 'is_admin': r[1]} for r in user_rows]
    conn.close()
    return jsonify({'status': 'success', 'history': history_list, 'users': users_list})

@app.route('/toggle_admin', methods=['POST'])
def toggle_admin():
    if 'user' not in session or session['user'].lower() != 'admin':
        return jsonify({'status': 'error', 'message': 'Chỉ tài khoản Master Admin gốc mới có quyền này!'})
    
    data = request.get_json()
    target_user = data.get('username')
    new_status = data.get('is_admin')

    if target_user.lower() == 'admin':
        return jsonify({'status': 'error', 'message': 'Không thể thay đổi quyền của Admin gốc!'})

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_admin=? WHERE username=?", (new_status, target_user))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success'})

@app.route('/get_history', methods=['GET'])
def get_history():
    if 'user' not in session:
        return jsonify({'status': 'error', 'history': []})
    
    is_adm = check_is_admin(session['user'])
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    
    if is_adm:
        cursor.execute("SELECT username, title, format, path, timestamp FROM history ORDER BY id DESC")
        rows = cursor.fetchall()
        history_list = [{'user': r[0], 'title': r[1], 'format': r[2], 'path': r[3], 'time': r[4]} for r in rows]
    else:
        cursor.execute("SELECT title, format, path, timestamp FROM history WHERE username=? ORDER BY id DESC", (session['user'],))
        rows = cursor.fetchall()
        history_list = [{'user': session['user'], 'title': r[0], 'format': r[1], 'path': r[2], 'time': r[3]} for r in rows]
        
    conn.close()
    return jsonify({'status': 'success', 'history': history_list, 'is_admin': is_adm})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Cyber Music Studio Server đang chạy tại cổng {port}")
    app.run(host='0.0.0.0', port=port)