import falcon
import sqlite3
import json
import os
import secrets
import urllib.parse
import requests
from pylxd import Client

# Load simple env vars without external libraries if python-dotenv isn't installed
def load_env():
    try:
        with open('../.env', 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#'):
                    key, val = line.strip().split('=', 1)
                    os.environ[key] = val
    except Exception:
        pass
load_env()

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '')
REDIRECT_URI = os.environ.get('GOOGLE_OAUTH_REDIRECT_URI', 'http://localhost:8000/auth/google/callback')
SESSION_SECRET = os.environ.get('SESSION_SECRET', 'dev-secret')
BOOTSTRAP_ADMIN_EMAIL = os.environ.get('BOOTSTRAP_ADMIN_EMAIL', '')

DB_PATH = 'app.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- Middleware for Auth ---
class AuthMiddleware:
    def process_request(self, req, resp):
        # Skip auth for CORS preflight (OPTIONS) and auth routes
        if req.method == 'OPTIONS' or req.path.startswith('/auth'):
            return
            
        token = req.cookies.get('session_token')
        if not token:
            raise falcon.HTTPUnauthorized(title='401 Unauthorized', description='Please log in.')
        
        # In a real app, this token would be a signed JWT. For this test, we assume the token is the user's email.
        # This is NOT secure for production, but suffices to demonstrate authorization flow.
        req.context.user_email = token
        
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (token,)).fetchone()
            if not user:
                raise falcon.HTTPUnauthorized(title='401 Unauthorized', description='User not found.')
            req.context.user = dict(user)

# --- Auth Resources ---
class AuthResource:
    def on_get_google_login(self, req, resp):
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={GOOGLE_CLIENT_ID}&"
            f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
            "response_type=code&"
            "scope=email profile"
        )
        raise falcon.HTTPFound(auth_url)

    def on_get_google_callback(self, req, resp):
        code = req.get_param('code')
        if not code:
            raise falcon.HTTPBadRequest(title="Missing code")

        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code"
        }
        
        token_res = requests.post(token_url, data=data).json()
        access_token = token_res.get('access_token')
        
        if not access_token:
            resp.text = json.dumps({"error": "Failed to get access token"})
            return
            
        user_info_res = requests.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {access_token}"}).json()
        email = user_info_res.get('email')

        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if not user:
                if email == BOOTSTRAP_ADMIN_EMAIL:
                    conn.execute("INSERT INTO users (email, role) VALUES (?, 'admin')", (email,))
                    conn.commit()
                else:
                    raise falcon.HTTPForbidden(title="Access Denied", description="You have not been invited.")
                    
        # Set a session cookie with path='/' so it is sent to all endpoints, not just /auth
        resp.set_cookie('session_token', email, max_age=86400, secure=False, http_only=True, path='/')
        
        # Redirect back to the Astro dashboard safely to preserve the cookie
        resp.status = falcon.HTTP_302
        resp.location = 'http://localhost:4321/dashboard'

# --- Container Resources ---
class ContainerListResource:
    def on_get(self, req, resp):
        user = req.context.user
        client = Client()
        
        with get_db() as conn:
            if user['role'] == 'admin':
                # Admins see all containers in DB
                assigned_containers = [row['lxd_name'] for row in conn.execute("SELECT lxd_name FROM containers").fetchall()]
            else:
                # Users only see what is assigned to them
                assigned_containers = [row['lxd_name'] for row in conn.execute("SELECT lxd_name FROM containers WHERE owner_id = ?", (user['id'],)).fetchall()]

        results = []
        for c in client.containers.all():
            if c.name in assigned_containers or user['role'] == 'admin':
                results.append({
                    "name": c.name,
                    "state": c.status,
                    "architecture": c.architecture
                })
        
        resp.text = json.dumps(results)
        resp.status = falcon.HTTP_200

    def on_post(self, req, resp):
        user = req.context.user
        if user['role'] != 'admin':
            raise falcon.HTTPForbidden(description="Only admins can create containers.")
            
        doc = req.get_media()
        name = doc.get('name')
        ram_mb = int(doc.get('ram_mb', 512))
        cpu_cores = int(doc.get('cpu_cores', 1))
        
        # Validation bounds
        if ram_mb < 256 or ram_mb > 4096:
            raise falcon.HTTPBadRequest(description="RAM must be between 256MB and 4096MB")
        if cpu_cores < 1 or cpu_cores > 4:
            raise falcon.HTTPBadRequest(description="CPU cores must be between 1 and 4")

        client = Client()
        config = {
            'name': name,
            'source': {
                'type': 'image',
                'mode': 'pull',
                'server': 'https://cloud-images.ubuntu.com/releases',
                'protocol': 'simplestreams',
                'alias': '24.04'
            },
            'limits.memory': f"{ram_mb}MB",
            'limits.cpu': str(cpu_cores)
        }
        
        try:
            client.containers.create(config, wait=True)
            with get_db() as conn:
                conn.execute("INSERT INTO containers (lxd_name) VALUES (?)", (name,))
                conn.execute("INSERT INTO audit_logs (user_id, action, target) VALUES (?, ?, ?)", (user['id'], 'create', name))
                conn.commit()
                
            resp.status = falcon.HTTP_201
            resp.text = json.dumps({"message": f"Container {name} created!"})
        except Exception as e:
            resp.status = falcon.HTTP_400
            resp.text = json.dumps({"error": str(e)})

class ContainerActionResource:
    def on_post(self, req, resp, name, action):
        user = req.context.user
        client = Client()
        
        # Authorization check
        with get_db() as conn:
            c_record = conn.execute("SELECT * FROM containers WHERE lxd_name = ?", (name,)).fetchone()
            if not c_record and user['role'] != 'admin':
                raise falcon.HTTPNotFound(description="Container not found in database.")
            if c_record and user['role'] != 'admin' and c_record['owner_id'] != user['id']:
                raise falcon.HTTPForbidden()

        try:
            container = client.containers.get(name)
            if action == 'start':
                container.start(wait=True)
            elif action == 'stop':
                container.stop(wait=True)
            elif action == 'delete':
                if user['role'] != 'admin':
                    raise falcon.HTTPForbidden(description="Only admins can delete containers.")
                container.delete(wait=True)
                with get_db() as conn:
                    conn.execute("DELETE FROM containers WHERE lxd_name = ?", (name,))
                    conn.commit()
            elif action == 'terminal':
                doc = req.get_media()
                cmd_string = doc.get('command', '')
                if not cmd_string:
                    raise falcon.HTTPBadRequest(title="No command provided")
                
                import shlex
                cmd_list = shlex.split(cmd_string)
                res = container.execute(cmd_list)
                
                resp.text = json.dumps({
                    "exit_code": res.exit_code,
                    "stdout": res.stdout,
                    "stderr": res.stderr
                })
                return
            else:
                raise falcon.HTTPBadRequest(title="Invalid Action")
                
            with get_db() as conn:
                conn.execute("INSERT INTO audit_logs (user_id, action, target) VALUES (?, ?, ?)", (user['id'], action, name))
                conn.commit()
                
            resp.text = json.dumps({"message": f"Container {name} {action}ed successfully."})
        except Exception as e:
            resp.status = falcon.HTTP_400
            resp.text = json.dumps({"error": str(e)})

class UsersResource:
    def on_post(self, req, resp):
        user = req.context.user
        if user['role'] != 'admin':
            raise falcon.HTTPForbidden()
            
        doc = req.get_media()
        email = doc.get('email')
        
        with get_db() as conn:
            try:
                conn.execute("INSERT INTO users (email, role) VALUES (?, 'user')", (email,))
                conn.commit()
                resp.text = json.dumps({"message": f"User {email} invited."})
            except sqlite3.IntegrityError:
                resp.status = falcon.HTTP_400
                resp.text = json.dumps({"error": "User already exists."})

from falcon import CORSMiddleware

cors = CORSMiddleware(
    allow_origins=['http://localhost:4321'],
    allow_credentials='*'
)

# --- App Setup ---
app = falcon.App(middleware=[cors, AuthMiddleware()])

app.add_route('/auth/login', AuthResource(), suffix='google_login')
app.add_route('/auth/google/callback', AuthResource(), suffix='google_callback')
app.add_route('/api/containers', ContainerListResource())
app.add_route('/api/containers/{name}/{action}', ContainerActionResource())
app.add_route('/api/users', UsersResource())

if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    print("Starting Falcon API server on http://localhost:8000...")
    with make_server('', 8000, app) as httpd:
        httpd.serve_forever()
