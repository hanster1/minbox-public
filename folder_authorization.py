"""Native Google Picker authorization for one owner-selected Drive folder."""
import re
import secrets
import time
import webbrowser
from html import escape
from urllib.parse import parse_qsl, urlsplit, urlunsplit
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler

FILE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
SCOPES = [FILE_SCOPE]
FOLDER_MIME = 'application/vnd.google-apps.folder'


class FolderAuthorizationError(ValueError):
    """A fixed, safe error message containing no OAuth response data."""


def _folder_id_from_url(value):
    """Accept a normal Drive folder link, never a permission or OAuth URL."""
    if not isinstance(value, str) or len(value) > 2048:
        raise FolderAuthorizationError('Paste the Google Drive folder link')
    parsed = urlsplit(value.strip())
    if (parsed.scheme != 'https' or parsed.netloc != 'drive.google.com' or parsed.fragment):
        raise FolderAuthorizationError('Paste the Google Drive folder link')
    match = re.fullmatch(r'/drive/(?:u/[0-9]+/)?folders/([A-Za-z0-9_-]{1,256})/?', parsed.path)
    if not match or match[1] == 'root':
        raise FolderAuthorizationError('Paste the Google Drive folder link')
    return match[1]


def _prepare_folder(timeout_seconds):
    """Browser-only preflight: create a folder, paste its link, then confirm it."""
    class PrivateHandler(WSGIRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def log_message(self, *args):
            pass
    class ExclusiveServer(WSGIServer):
        allow_reuse_address = False
    csrf = secrets.token_urlsafe(32)
    folder = None
    completed = False
    origin = ''

    def respond(start_response, body, status='200 OK'):
        start_response(status, [('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"),
            # Basic browser form POSTs get Origin:null under no-referrer.
            # Keep the local origin for validation while suppressing external refs.
            ('Referrer-Policy', 'same-origin')])
        return [('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Minbox — choose your archive folder</title><main><h1>Choose your Minbox folder</h1>'''
                 + body + '</main></html>').encode()]

    def instructions(start_response, message=''):
        return respond(start_response, f'''<p>{escape(message)}</p>
<p>For a new archive, before connecting Google, create a new empty, private folder in your Google Drive.
Name it anything you like. Minbox will keep that name and put your archive documents inside it.</p>
<p><strong>You can safely rename this folder at any time in Google Drive.</strong>
Minbox will stay connected because it uses the folder's ID.</p>
<p>Reconnecting an existing Minbox archive? Use the same folder already connected to that archive.
Do not create a replacement folder. Its existing documents and folder name will be kept.</p>
<p><a href="https://drive.google.com/drive/my-drive" target="_blank" rel="noopener noreferrer">Open Google Drive to create your folder</a></p>
<p>For a new archive, in Drive choose New → New folder. Open your chosen folder and copy its link from the address bar.</p>
<form method="post" action="/">
<input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="step" value="folder">
<label>Paste your chosen folder link <input type="url" name="folder_url" maxlength="2048" required></label>
<button type="submit">Show my chosen folder</button></form>''')

    def application(environ, start_response):
        nonlocal folder, completed
        if environ.get('HTTP_HOST') != urlsplit(origin).netloc or environ.get('PATH_INFO') != '/':
            return respond(start_response, '<p>Page not found.</p>', '404 Not Found')
        method = environ.get('REQUEST_METHOD')
        if method == 'GET':
            return instructions(start_response)
        if method != 'POST':
            return respond(start_response, '<p>Request not allowed.</p>', '405 Method Not Allowed')
        try:
            if (environ.get('HTTP_ORIGIN') != origin or environ.get('HTTP_TRANSFER_ENCODING') or
                    environ.get('CONTENT_TYPE', '').split(';')[0] != 'application/x-www-form-urlencoded'):
                raise ValueError
            length = int(environ.get('CONTENT_LENGTH', '0'))
            if not 0 < length <= 4096:
                raise ValueError
            body = environ['wsgi.input'].read(length)
            if len(body) != length:
                raise ValueError
            pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=4)
            params = dict(pairs)
            if len(pairs) != len(params) or not secrets.compare_digest(params.get('csrf', ''), csrf):
                raise ValueError
            if params.get('step') == 'folder' and set(params) == {'csrf', 'step', 'folder_url'}:
                folder = _folder_id_from_url(params['folder_url'])
                link = 'https://drive.google.com/drive/folders/' + folder
                return respond(start_response, f'''<p>Your chosen archive folder:</p>
<p><a href="{link}" target="_blank" rel="noopener noreferrer">{link}</a></p>
<p><strong>You can safely rename this folder at any time in Google Drive.</strong>
Minbox will stay connected because it uses the folder's ID.</p>
<p>Check that this is your new empty, private folder, or the same folder for an existing archive.
Next, sign in to Google and select only this folder.
Minbox requests access only to files you select and the archive documents it creates.</p>
<form method="post" action="/"><input type="hidden" name="csrf" value="{csrf}">
<input type="hidden" name="step" value="confirm"><input type="hidden" name="folder_id" value="{folder}">
<button type="submit">Continue to Google — select only this folder</button></form>
<p><a href="/">Choose a different folder</a></p>''')
            if (params.get('step') == 'confirm' and set(params) == {'csrf', 'step', 'folder_id'} and
                    folder is not None and params['folder_id'] == folder):
                completed = True
                link = 'https://drive.google.com/drive/folders/' + folder
                return respond(start_response, f'<p>Chosen folder: <a href="{link}">{link}</a></p>'
                    '<p>Google Picker will open next. Select only this folder, then return to Minbox.</p>')
            raise ValueError
        except FolderAuthorizationError:
            return instructions(start_response, 'Paste a link to a folder on drive.google.com.')
        except (ValueError, UnicodeError, KeyError, OSError, TypeError):
            return respond(start_response, '<p>Request could not be accepted. Reload Minbox and try again.</p>', '400 Bad Request')

    with make_server('127.0.0.1', 0, application, server_class=ExclusiveServer,
                     handler_class=PrivateHandler) as server:
        origin = f'http://127.0.0.1:{server.server_port}'
        if not webbrowser.open(origin + '/', new=1, autoraise=True):
            raise FolderAuthorizationError('Open the Minbox setup browser on this computer')
        deadline = time.monotonic() + timeout_seconds
        while not completed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FolderAuthorizationError('Minbox folder setup timed out; retry connecting')
            server.timeout = min(remaining, 1)
            server.handle_request()
    return folder


def _run_local_picker(flow, **options):
    """Use public OAuth methods; preserve query bytes and suppress callback logs.

    The library's local-server helper replaces every 'http' substring, including
    the HTTPS scope in Picker callbacks. Only the callback scheme may change.
    """
    class PrivateHandler(WSGIRequestHandler):
        def log_message(self, *args):
            pass
    class ExclusiveServer(WSGIServer):
        allow_reuse_address = False
    completed, failure = False, None
    def callback(environ, start_response):
        nonlocal completed, failure
        if environ.get('PATH_INFO') != '/' or environ.get('REQUEST_METHOD') != 'GET':
            start_response('404 Not Found', [('Content-Type','text/plain')])
            return [b'Not found.']
        query = environ.get('QUERY_STRING','')
        try:
            if len(query) > 16384:
                raise FolderAuthorizationError('Google authorization callback is invalid')
            redirect = urlsplit(flow.redirect_uri)
            response = urlunsplit(('https', redirect.netloc, redirect.path, query, ''))
            flow.fetch_token(authorization_response=response, timeout=20)
        except Exception:
            failure = FolderAuthorizationError('Google archive selection failed; retry authorization')
            completed = True
            start_response('400 Bad Request', [('Content-Type','text/plain'),('Cache-Control','no-store')])
            return [b'Authorization could not be completed. Return to Minbox and retry.']
        completed = True
        start_response('200 OK', [('Content-Type','text/plain'),('Cache-Control','no-store')])
        return [options['success_message'].encode()]
    with make_server('127.0.0.1', 0, callback, server_class=ExclusiveServer,
                     handler_class=PrivateHandler) as server:
        flow.redirect_uri = f'http://127.0.0.1:{server.server_port}/'
        arguments = {k:v for k,v in options.items() if k not in
                     {'host','bind_addr','port','open_browser','authorization_prompt_message',
                      'success_message','timeout_seconds'}}
        url, _ = flow.authorization_url(**arguments)
        if not webbrowser.open(url, new=1, autoraise=True):
            raise FolderAuthorizationError('Open the Google authorization browser on this computer')
        deadline = time.monotonic() + options['timeout_seconds']
        while not completed:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FolderAuthorizationError('Google authorization timed out; retry authorization')
            server.timeout = min(remaining, 1)
            server.handle_request()
        if failure:
            raise failure
    return flow.credentials


def require_file_scope(scopes):
    values = scopes.split() if isinstance(scopes, str) else scopes
    if not isinstance(values, (list, tuple, set)) or list(values) != SCOPES:
        raise FolderAuthorizationError('Google must grant only selected-file access')


def _guard_callback(flow, expected_ids=None, expected_folder_id=None):
    """Keep library-owned state, PKCE and exchange; validate Picker data first."""
    authorization_url = flow.authorization_url
    fetch_token = flow.fetch_token
    selection = {}

    def guarded_url(**kwargs):
        url, state = authorization_url(**kwargs)
        if not isinstance(state, str) or not state:
            raise FolderAuthorizationError('Google authorization state is missing')
        selection['state'] = state
        return url, state

    def guarded_fetch(**kwargs):
        response = kwargs.get('authorization_response')
        if not isinstance(response, str) or len(response) > 16384:
            raise FolderAuthorizationError('Google folder selection is missing')
        parsed = urlsplit(response)
        redirect = urlsplit(flow.redirect_uri)
        # run_local_server changes the callback scheme to HTTPS for oauthlib.
        if (parsed.scheme != 'https' or parsed.netloc != redirect.netloc or
                parsed.path != redirect.path or parsed.fragment):
            raise FolderAuthorizationError('Google authorization callback is invalid')
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=16)
        params = dict(pairs)
        if len(params) != len(pairs):
            raise FolderAuthorizationError('Google authorization callback is invalid')
        state = params.get('state', '')
        if not state or not secrets.compare_digest(state, selection.get('state', '')):
            raise FolderAuthorizationError('Google authorization state does not match')
        if 'error' in params:
            raise FolderAuthorizationError('Google folder authorization was cancelled')
        require_file_scope(params.get('scope'))
        picked = params.get('picked_file_ids', '').split(',')
        if (not picked or len(picked) != len(set(picked)) or
                any(not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', item) or item == 'root' for item in picked)):
            raise FolderAuthorizationError('Google archive selection is invalid')
        if expected_ids is None and len(picked) != 1:
            raise FolderAuthorizationError('Select exactly one archive folder')
        if expected_folder_id is not None and picked != [expected_folder_id]:
            raise FolderAuthorizationError('Select only the folder you chose in Minbox')
        if expected_ids is not None and set(picked) != set(expected_ids):
            raise FolderAuthorizationError('Select all existing archive items shown for migration')
        if not params.get('code'):
            raise FolderAuthorizationError('Google authorization code is missing')
        token = fetch_token(**kwargs)
        require_file_scope(token.get('scope'))
        selection['folder_id'] = picked[0]
        selection['selected_ids'] = picked
        return token

    flow.authorization_url = guarded_url
    flow.fetch_token = guarded_fetch
    return selection


def authorize_folder(client_file, timeout_seconds=300):
    """Return credentials and an ID only after a narrow, validated Picker grant."""
    if not 1 <= timeout_seconds <= 900:
        raise FolderAuthorizationError('Authorization timeout must be between 1 and 900 seconds')
    try:
        expected_folder = _prepare_folder(timeout_seconds)
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_file), scopes=SCOPES, autogenerate_code_verifier=True)
        selection = _guard_callback(flow, expected_folder_id=expected_folder)
        credentials = _run_local_picker(flow,
            host='127.0.0.1', bind_addr='127.0.0.1', port=0, open_browser=True,
            authorization_prompt_message='',
            success_message='Authorization received. Return to Minbox to check the result.',
            access_type='offline', prompt='consent', trigger_onepick='true',
            allow_multiple='false', mimetypes=FOLDER_MIME,
            allow_folder_selection='true', include_granted_scopes='false',
            file_ids=expected_folder,
            timeout_seconds=timeout_seconds)
        require_file_scope(credentials.granted_scopes)
        if not credentials.refresh_token:
            raise FolderAuthorizationError('Google did not return an offline refresh credential')
        return credentials, selection['folder_id']
    except FolderAuthorizationError:
        raise
    except Exception:
        raise FolderAuthorizationError('Google folder authorization failed; try connecting again') from None


def authorize_existing_items(client_file, identifiers, timeout_seconds=600):
    """Migration-only approval of a fixed inventory, never arbitrary extra files."""
    identifiers = list(identifiers)
    if (not 1 <= len(identifiers) <= 100 or len(set(identifiers)) != len(identifiers) or
            any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', item) or item == 'root' for item in identifiers) or
            not 1 <= timeout_seconds <= 900):
        raise FolderAuthorizationError('Migration selection is invalid')
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=SCOPES,
                                                        autogenerate_code_verifier=True)
        selection = _guard_callback(flow, identifiers)
        credentials = _run_local_picker(flow, host='127.0.0.1', bind_addr='127.0.0.1', port=0,
            open_browser=True, authorization_prompt_message='',
            success_message='Authorization received. Return to Minbox to check the migration.',
            access_type='offline', prompt='consent', trigger_onepick='true',
            allow_multiple='true', allow_folder_selection='true', include_granted_scopes='false',
            mimetypes=FOLDER_MIME+',application/vnd.google-apps.document',
            file_ids=','.join(identifiers), timeout_seconds=timeout_seconds)
        require_file_scope(credentials.granted_scopes)
        if not credentials.refresh_token:
            raise FolderAuthorizationError('Google did not return an offline refresh credential')
        return credentials, selection['selected_ids']
    except FolderAuthorizationError:
        raise
    except Exception:
        raise FolderAuthorizationError('Google archive authorization failed; try migrating again') from None
