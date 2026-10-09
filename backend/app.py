import falcon
import sqlite3
import json
from pylxd import Client

DB_PATH = 'app.db'

# --- Middleware for Auth ---
class AuthMiddleware:
    def process_request(self, req, resp):
        # We will check session cookies here.
        # For now, we skip auth for the auth routes themselves.
        if req.path.startswith('/auth'):
            return
            
        # Example pseudo-check
        # token = req.cookies.get('session_token')
        # if not token:
        #     raise falcon.HTTPUnauthorized(title='401 Unauthorized', description='Please log in.')
        pass

# --- API Resources ---

class AuthResource:
    def on_get_google_login(self, req, resp):
        # Redirect user to Google OAuth URL
        resp.text = json.dumps({"message": "Redirecting to Google OAuth..."})
        resp.status = falcon.HTTP_200

    def on_get_google_callback(self, req, resp):
        # Handle the callback from Google, create user in DB, set session cookie
        resp.text = json.dumps({"message": "OAuth successful!"})
        resp.status = falcon.HTTP_200

class ContainerListResource:
    def on_get(self, req, resp):
        client = Client()
        containers = []
        for c in client.containers.all():
            containers.append({
                "name": c.name,
                "state": c.status,
                "architecture": c.architecture
            })
        resp.text = json.dumps(containers)
        resp.status = falcon.HTTP_200

    def on_post(self, req, resp):
        # Create a new container
        doc = req.get_media()
        # TODO: Validate RAM/CPU bounds here!
        client = Client()
        
        config = {
            'name': doc.get('name'),
            'source': {'type': 'image', 'alias': doc.get('image', 'ubuntu/24.04')},
            'limits.memory': f"{doc.get('ram_mb', 512)}MB",
            'limits.cpu': str(doc.get('cpu_cores', 1))
        }
        
        try:
            client.containers.create(config, wait=True)
            resp.status = falcon.HTTP_201
            resp.text = json.dumps({"message": f"Container {doc.get('name')} created!"})
        except Exception as e:
            resp.status = falcon.HTTP_400
            resp.text = json.dumps({"error": str(e)})

class ContainerActionResource:
    def on_post(self, req, resp, name, action):
        client = Client()
        try:
            container = client.containers.get(name)
            if action == 'start':
                container.start(wait=True)
            elif action == 'stop':
                container.stop(wait=True)
            elif action == 'delete':
                container.delete(wait=True)
            else:
                raise falcon.HTTPBadRequest(title="Invalid Action")
                
            resp.text = json.dumps({"message": f"Container {name} {action}ed successfully."})
        except Exception as e:
            resp.status = falcon.HTTP_400
            resp.text = json.dumps({"error": str(e)})

class TerminalResource:
    def on_post(self, req, resp, name):
        doc = req.get_media()
        command = doc.get('command')
        
        client = Client()
        try:
            container = client.containers.get(name)
            # Execute command safely
            exit_code, stdout, stderr = container.execute(command.split())
            resp.text = json.dumps({
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr
            })
        except Exception as e:
            resp.status = falcon.HTTP_400
            resp.text = json.dumps({"error": str(e)})

# --- App Setup ---
app = falcon.App(middleware=[AuthMiddleware()])

# Routes
app.add_route('/auth/login', AuthResource(), suffix='google_login')
app.add_route('/auth/callback', AuthResource(), suffix='google_callback')
app.add_route('/api/containers', ContainerListResource())
app.add_route('/api/containers/{name}/{action}', ContainerActionResource())
app.add_route('/api/containers/{name}/terminal', TerminalResource())

if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    print("Starting Falcon API server on http://localhost:8000...")
    with make_server('', 8000, app) as httpd:
        httpd.serve_forever()
