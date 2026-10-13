#!/usr/bin/env python3
"""Connect an archive owner's Drive to one private folder selected in Google Picker."""
import argparse
import json
import os
import tempfile
from pathlib import Path
from storage import _owner, _outside_git
from archive_io import GoogleAuth, _http_request
from publisher_status import private_path
from folder_authorization import SCOPES, FOLDER_MIME, authorize_folder


def _stage_json(directory, data):
    fd, name = tempfile.mkstemp(prefix='.google-connect-', dir=directory)
    path = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client_file',type=Path,help='Desktop OAuth client JSON; keep outside Git')
    parser.add_argument('--owner',type=_owner,required=True)
    parser.add_argument('--config-dir',type=Path,default=Path.home()/'.config/minbox-text-archive/owners')
    parser.add_argument('--account-email',help='Expected Google account; existing bindings are also enforced')
    parser.add_argument('--timeout-seconds',type=int,default=300)
    args=parser.parse_args(argv)
    directory=args.config_dir.expanduser().absolute()/args.owner
    _outside_git(directory)
    if any(p.is_symlink() for p in (directory,*directory.parents)):
        parser.error('Owner configuration path must not contain symlinks')
    directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
    config_path=directory/'drive.json';target=directory/'google-authorized-user.json'
    previous=json.loads(config_path.read_text()) if config_path.exists() else {}
    if previous and previous.get('owner')!=args.owner:
        parser.error('Existing Drive configuration belongs to a different owner')
    if previous.get('credentials_file'):
        target=private_path(previous['credentials_file'])
    for path in (config_path,target):
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_mode & 0o077)):
            parser.error('Existing owner files must be private regular files')
    credentials,folder=authorize_folder(args.client_file.expanduser(),args.timeout_seconds)
    bound_folder=previous.get('archive_root_folder_id') or previous.get('folder_id')
    if bound_folder and bound_folder != folder:
        raise ValueError('Archive folder mismatch; previous credentials preserved')
    if previous.get('folder_id') and previous.get('folder_id') != folder:
        raise ValueError('Archive folder mismatch; previous credentials preserved')
    value=json.loads(credentials.to_json());value['type']='authorized_user'
    staged=_stage_json(directory,value)
    try:
        # Verify the actual refreshed grant before replacing an existing grant.
        auth=GoogleAuth(staged,scopes=SCOPES)
        token=auth.token()
        _verify_folder_and_save(args,previous,folder,token,staged,target,config_path,directory)
    finally:
        staged.unlink(missing_ok=True)
    print('Drive connected for '+args.owner+'. Credentials remain private.')
    print('Archive folder: https://drive.google.com/drive/folders/'+folder)
    print('Choose a bounded publisher scope and its private Docs before enabling publication.')


def _verify_folder_and_save(args,previous,folder,token,staged,target,config_path,directory):
    def request(method,suffix,body=None):
        return _http_request(method,'https://www.googleapis.com/drive/v3/'+suffix,body,
                             {'Authorization':'Bearer '+token,'Content-Type':'application/json'},20)
    email=request('GET','about?fields=user(emailAddress)')['user']['emailAddress']
    if any(expected and expected.lower()!=email.lower() for expected in
           (args.account_email,previous.get('google_account_email'))):
        raise ValueError('Google account mismatch; previous credentials preserved')
    metadata=request('GET','files/'+folder+'?fields=id,mimeType,shared,trashed,driveId,parents,owners(emailAddress),capabilities(canEdit)')
    if (folder=='root' or metadata.get('id')!=folder or metadata.get('shared') is not False or
            metadata.get('trashed') is not False or metadata.get('driveId') or not metadata.get('parents') or
            metadata.get('mimeType')!=FOLDER_MIME or metadata.get('capabilities',{}).get('canEdit') is not True or
            not any(o.get('emailAddress','').lower()==email.lower() for o in metadata.get('owners',[]))):
        raise ValueError('Selected archive folder must be private, editable, and owned by this account')
    config=dict(previous)
    config.update({'owner':args.owner,'google_account_email':email,'credentials_file':str(target),
                   'google_scopes':SCOPES,'folder_id':folder,'archive_root_folder_id':folder,
                   'folder_access':'selected_folder'})
    pending_config=_stage_json(directory,config)
    backups={}
    replaced=[]
    try:
        for path in (target,config_path):
            if path.exists():
                fd,name=tempfile.mkstemp(prefix='.google-previous-',dir=directory)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(path.read_bytes())
                backups[path]=Path(name)
            else:
                backups[path]=None
        for temporary,path in ((staged,target),(pending_config,config_path)):
            os.replace(temporary,path)
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            backup=backups[path]
            if backup is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(backup,path)
        raise
    finally:
        pending_config.unlink(missing_ok=True)
        for backup in backups.values():
            if backup is not None:
                backup.unlink(missing_ok=True)


if __name__=='__main__':
    main()
