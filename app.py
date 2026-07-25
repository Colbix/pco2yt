import os
import json
import datetime
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import requests

# Google OAuth & API client modules
import google_auth_oauthlib.flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24).hex()

if os.environ.get("USE_PROXY", "").lower() == "true":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_host=1, x_proto=1)

app.config['UPLOAD_FOLDER'] = '/tmp'

PCO_CLIENT_ID = os.environ.get("PCO_CLIENT_ID")
PCO_SECRET = os.environ.get("PCO_SECRET")
TARGET_TZ_STR = os.environ.get("TARGET_TIMEZONE", "America/New_York")
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

CLIENT_SECRETS_FILE = "/app/client_secrets.json"
TOKEN_FILE = "/app/token.json"
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def ensure_token_file_exists():
    """Ensures that the token file path exists and is initialized if missing."""
    if not os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, 'w') as f:
                json.dump({}, f)
        except Exception as e:
            print(f"Error initializing {TOKEN_FILE}: {e}")

def get_pco_metadata(target_date):
    """
    Fetches the plan matching the target_date by using target date window boundaries.
    """
    fallback_meta = {
        "title": f"Service - {target_date}", 
        "description": f"Date: {target_date}",
        "thumbnail_url": None
    }

    if not PCO_CLIENT_ID or not PCO_SECRET:
        print("Warning: PCO_CLIENT_ID or PCO_SECRET is missing.")
        return fallback_meta

    auth = (PCO_CLIENT_ID, PCO_SECRET)
    
    try:
        # 1. Parse date input into expected display formats and boundary strings
        dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
        
        # Build string matches without OS-dependent formatting flags
        day_str = str(dt_obj.day)
        pco_dates_format = f"{dt_obj.strftime('%B')} {day_str}, {dt_obj.strftime('%Y')}" # e.g. "July 12, 2026"
        pco_short_dates_format = f"{dt_obj.strftime('%b')} {day_str}"                   # e.g. "Jul 12"

        # Create a +/- 2 day query window boundary around the target date
        after_date = (dt_obj - timedelta(days=2)).strftime("%Y-%m-%d")
        before_date = (dt_obj + timedelta(days=2)).strftime("%Y-%m-%d")

        # 2. Fetch all Service Types first
        st_url = "https://api.planningcenteronline.com/services/v2/service_types"
        st_res = requests.get(st_url, auth=auth, timeout=10)

        if st_res.status_code != 200:
            print(f"[PCO Error] HTTP {st_res.status_code}: {st_res.text}")
            return fallback_meta

        service_types = st_res.json().get('data', [])
        target_plan = None
        matched_service_type_id = None

        # 3. Iterate through Service Types and fetch plans scoped by date window boundary
        for st in service_types:
            st_id = st.get('id')
            
            # Request only plans bounded within the specified timeframe
            plans_url = (
                f"https://api.planningcenteronline.com/services/v2/service_types/{st_id}/plans"
                f"?filter=after&after={after_date}&before={before_date}&per_page=10"
            )
            plans_res = requests.get(plans_url, auth=auth, timeout=10)

            if plans_res.status_code != 200:
                print(f"[PCO Warning] Could not fetch plans for Service Type {st_id}: HTTP {plans_res.status_code}")
                continue

            plans = plans_res.json().get('data', [])

            for plan in plans:
                attr = plan.get('attributes', {})
                dates_val = attr.get('dates', '')
                short_dates_val = attr.get('short_dates', '')

                # Match date against PCO string fields
                if (dates_val == pco_dates_format or 
                    short_dates_val == pco_short_dates_format or
                    pco_dates_format in dates_val):
                    
                    target_plan = plan
                    matched_service_type_id = st_id
                    print(f"[PCO Debug] Found matching plan ID {plan.get('id')} under Service Type {st_id}")
                    break

            if target_plan:
                break

        if not target_plan:
            print(f"[PCO Warning] No plan found matching date: {target_date}")
            return fallback_meta

        plan_id = target_plan['id']
        attr = target_plan.get('attributes', {})
        title = attr.get('title') or "Sunday Service"
        series_name = attr.get('series_title') or "Sermon Series"

        # 4. Fetch Plan Attachments for Artwork Thumbnail
        attachments_url = f"https://api.planningcenteronline.com/services/v2/service_types/{matched_service_type_id}/plans/{plan_id}/attachments"
        attachments_res = requests.get(attachments_url, auth=auth, timeout=10)

        thumbnail_url = None

        if attachments_res.status_code == 200:
            attachments = attachments_res.json().get('data', [])
            for attach in attachments:
                if attach.get('type') == 'Attachment':
                    attach_attr = attach.get('attributes', {})
                    filetype = attach_attr.get('filetype', '').lower()
                    content_type = attach_attr.get('content_type', '').lower()
                    
                    is_image = filetype == 'image' or 'image/' in content_type
                    
                    if is_image:
                        thumbnail_url = attach_attr.get('thumbnail_url') or attach_attr.get('url')
                        print(f"[PCO Debug] Found Image Attachment: {attach_attr.get('filename')} -> {thumbnail_url}")
                        if thumbnail_url:
                            break

        # 5. Fetch Notes attached to the plan (Livestream section)
        notes_url = f"https://api.planningcenteronline.com/services/v2/service_types/{matched_service_type_id}/plans/{plan_id}/notes"
        notes_res = requests.get(notes_url, auth=auth, timeout=10)

        livestream_content = ""

        if notes_res.status_code == 200:
            notes_data = notes_res.json().get('data', [])
            for note in notes_data:
                attributes = note.get('attributes', {})
                category_name = attributes.get('category_name')
                
                if category_name and category_name.strip().lower() == "livestream":
                    livestream_content = attributes.get('content', '')
                    break

        # Construct description output
        #description = f"Service details for {target_date}.\nSeries: {series_name}\nTitle: {title}"

        if livestream_content:
            #description += f"\n\n--- Livestream Summary ---\n{livestream_content}"
            description = f"{livestream_content}"

        return {
            "title": f"{series_name} - {title} ({target_date})",
            "description": description,
            "thumbnail_url": thumbnail_url
        }

    except Exception as e:
        print(f"Error fetching PCO metadata: {e}")
        return fallback_meta

def get_credentials():
    """Helper to load and refresh credentials if they exist."""
    ensure_token_file_exists()
    credentials = None
    
    if os.path.getsize(TOKEN_FILE) > 0:
        with open(TOKEN_FILE, 'r') as f:
            try:
                raw_data = json.load(f)
            except json.JSONDecodeError:
                raw_data = {}
        if raw_data and "token" in raw_data:
            credentials = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(credentials.to_json())
        except Exception as refresh_err:
            print(f"Token refresh failed: {refresh_err}")
            return None
            
    if credentials and credentials.valid:
        return credentials
    return None

def upload_to_youtube(file_path, metadata, publish_date, publish_time_str, credentials):
    youtube = build("youtube", "v3", credentials=credentials)
    
    time_parts = [int(x) for x in publish_time_str.split(":")]
    if len(time_parts) == 2:
        time_parts.append(0)

    date_parts = [int(x) for x in publish_date.split("-")]
    
    localized_dt = datetime(
        date_parts[0], date_parts[1], date_parts[2], 
        time_parts[0], time_parts[1], time_parts[2],
        tzinfo=ZoneInfo(TARGET_TZ_STR)
    )
    publish_time_iso = localized_dt.isoformat()
    
    body = {
        'snippet': {
            'title': metadata['title'],
            'description': metadata['description'],
            'tags': ['church', 'sermon'],
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'private',
            'publishAt': publish_time_iso
        }
    }
    
    print(f"Initializing upload stream for: {file_path}")
    media = MediaFileUpload(file_path, chunksize=1024*1024, resumable=True, mimetype='video/*')
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    
    video_response = None
    while video_response is None:
        status, video_response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%...")
        
    video_id = video_response.get('id')
    print(f"Video uploaded successfully. ID: {video_id}")
    
    if metadata.get('thumbnail_url'):
        try:
            print(f"Downloading PCO artwork: {metadata['thumbnail_url']}")
            img_data = requests.get(metadata['thumbnail_url'], timeout=10).content
            
            upload_dir = app.config.get('UPLOAD_FOLDER', './') if 'app' in globals() else './'
            thumb_path = os.path.join(upload_dir, f"thumb_{video_id}.jpg")
            
            with open(thumb_path, 'wb') as f:
                f.write(img_data)
                
            print("Binding thumbnail graphic to YouTube video asset...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path, mimetype='image/jpeg')
            ).execute()
            
            os.remove(thumb_path)
            print("Thumbnail linked successfully!")
        except Exception as thumb_err:
            print(f"Warning: Video asset created, but thumbnail linkage failed: {thumb_err}")
            
    return video_response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/check-auth', methods=['GET'])
def check_auth():
    creds = get_credentials()
    return jsonify({"authenticated": creds is not None})

@app.route('/logout', methods=['POST'])
def logout():
    """Removes stored tokens to force a login/account switch."""
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        ensure_token_file_exists()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/pco-preview', methods=['GET'])
def pco_preview():
    target_date = request.args.get('date')
    if not target_date:
        return jsonify({"error": "Date parameter missing"}), 400
    metadata = get_pco_metadata(target_date)
    return jsonify(metadata)

@app.route('/auth')
def auth():
    try:
        if not os.path.exists(CLIENT_SECRETS_FILE):
            return f"CRITICAL ERROR: Google client secrets file not found at: {CLIENT_SECRETS_FILE}. Check your Docker volume mounts.", 500

        redirect_uri = f"{request.url_root.rstrip('/')}/oauth2callback"
        
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE, 
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )

        flow.code_verifier = STATIC_CODE_VERIFIER

        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return redirect(authorization_url)
        
    except Exception as e:
        print(f"CRITICAL ERROR inside /auth route: {str(e)}")
        import traceback
        traceback.print_exc()
        return f"Internal Authorization Boot Error: {str(e)}", 500

@app.route('/oauth2callback')
def oauth2callback():
    redirect_uri = f"{request.url_root.rstrip('/')}/oauth2callback"

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, 
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    flow.fetch_token(
        authorization_response=request.url,
        code_verifier=STATIC_CODE_VERIFIER
    )
    
    credentials = flow.credentials
    ensure_token_file_exists()
    with open(TOKEN_FILE, 'w') as token:
        token.write(credentials.to_json())
        
    return '<script>window.opener.location.reload(); window.close();</script>'

@app.route('/upload', methods=['POST'])
def handle_upload():
    creds = get_credentials()
    if not creds:
        return jsonify({"error": "Unauthorized. Please authenticate first."}), 401

    if 'video' not in request.files or 'date' not in request.form:
        return jsonify({"error": "Missing components"}), 400
        
    video_file = request.files['video']
    selected_date = request.form['date']
    publish_date = request.form.get('publish_date', selected_date)
    publish_time_str = request.form.get('publish_time', '13:00')
    
    filename = secure_filename(video_file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    video_file.save(filepath)
    
    metadata = get_pco_metadata(selected_date)
    
    try:
        yt_response = upload_to_youtube(filepath, metadata, publish_date, publish_time_str, creds)
        os.remove(filepath)
        return jsonify({"success": True, "videoId": yt_response.get('id'), "metadata": metadata})
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/test-connections', methods=['GET'])
def test_connections():
    status = {}
    
    try:
        pco_res = requests.get(
            "https://api.planningcenteronline.com/services/v2/service_types", 
            auth=(PCO_CLIENT_ID, PCO_SECRET),
            timeout=5
        )
        if pco_res.status_code == 200:
            status['planning_center'] = "SUCCESS: Authenticated and Connected."
        else:
            status['planning_center'] = f"FAILED: Status Code {pco_res.status_code} ({pco_res.text})"
    except Exception as e:
        status['planning_center'] = f"FAILED: Network Error ({str(e)})"
        
    try:
        creds = get_credentials()
        if not creds:
            status['youtube'] = "FAILED: YouTube authentication required or token.json is empty."
        else:
            youtube = build('youtube', 'v3', credentials=creds)
            request_test = youtube.videoCategories().list(
                part="snippet",
                regionCode="US"
            )
            response = request_test.execute()
            status['youtube'] = "SUCCESS: Authenticated and Connected. YouTube API is ready for uploads."
            
    except Exception as e:
        status['youtube'] = f"FAILED: {str(e)}"
        
    return jsonify(status)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)