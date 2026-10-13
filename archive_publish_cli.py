"""Run the private Drive archive publisher with existing owner authorization."""
import argparse
import fcntl
import json
import os
import sys
from folder_policy import verify_selected_folders
from archive_analysis import ArchiveAnalyzer
from archive_drive import DocsClient
from archive_publisher import run
from archive_snapshot import snapshot
from archive_io import GoogleAuth, _http_request
from publisher_status import PublisherStatus, failure_details, private_path


def verify_destinations(config, account, get):
    """Outputs stay in the work folder; only the shared input has its own binding."""
    folder = config['folder_id']
    correction_folder = config.get('corrections_folder_id', folder)
    base = 'https://www.googleapis.com/drive/v3/files/'
    fields = '?fields=id,mimeType,parents,shared,trashed,owners(emailAddress),capabilities(canEdit)'
    selected = verify_selected_folders(config, account, lambda identifier: get(base + identifier + fields))
    for identifier in (() if selected else {folder, correction_folder}):
        metadata = get(base + identifier + fields)
        if (metadata.get('mimeType') != 'application/vnd.google-apps.folder' or
                metadata.get('shared') or metadata.get('trashed') or
                not metadata.get('capabilities', {}).get('canEdit') or
                not any(o.get('emailAddress') == account for o in metadata.get('owners', []))):
            raise ValueError('publisher folder must remain private and owner-matched')
    for kind, document in config['documents'].items():
        expected = correction_folder if kind == 'corrections' else folder
        metadata = get(base + document + fields)
        if (metadata.get('mimeType') != 'application/vnd.google-apps.document' or
                metadata.get('shared') or metadata.get('trashed') or
                metadata.get('parents') != [expected] or
                not metadata.get('capabilities', {}).get('canEdit') or
                not any(o.get('emailAddress') == account for o in metadata.get('owners', []))):
            raise ValueError('publisher destination must remain private, editable, owner-matched and in its configured folder')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    args=parser.parse_args(argv)
    config_path=private_path(args.config)
    if config_path.is_symlink() or config_path.stat().st_mode & 0o777 != 0o600:
        raise ValueError('publisher configuration must be private')
    config=json.loads(config_path.read_text())

    lock_path=private_path(config['analysis_path']).with_suffix('.publisher.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd=os.open(lock_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a+b') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status': 'already_running'}, sort_keys=True))
            return 0
        with PublisherStatus(private_path(config['analysis_path']).with_suffix('.last-run.json')) as status:
            auth=GoogleAuth(config['credentials_file'],scopes=config.get('google_scopes'))
            def get(url):
                return _http_request('GET',url,None,{'Authorization':'Bearer '+auth.token()},20)
            account=get('https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)')['user']['emailAddress']
            if account.lower() != config['google_account_email'].lower():
                raise ValueError('connected Google account differs from the configured owner binding')
            verify_destinations(config, account, get)
            client=DocsClient(config['documents'].values(),token_provider=auth.token,
                              write_ids=[v for k,v in config['documents'].items() if k!='corrections'])
            config['analysis_policy']='archive-work-v1:'+config.get('model','gpt-6.1-sol')
            analyzer=ArchiveAnalyzer(model=config.get('model','gpt-6.1-sol'),executable=config.get('model_executable','codex'),timeout=120)
            status.phase('snapshot')
            current=snapshot(config['archive_root'],config['owner'],config['conversations'],config['start_date'])
            status.phase('publishing', current['latest_import'])
            result=run(config,current,client,analyzer)
            safe={'writes':result['writes'],'work_messages':result['work_messages'],'work_looms':result['work_looms'],
                  'deferred_sources':sum(len(result[k].get('deferred',[])) for k in ['message_analysis','loom_analysis']),
                  'model_calls':sum(result[k].get('model_calls',0) for k in ['message_analysis','loom_analysis']),
                  'analysis_failed_or_paused':any(result[k].get('analysis_failed') or result[k].get('paused') for k in ['message_analysis','loom_analysis'])}
            safe.update({key: result[key] for key in ('analysis_state', 'analysis_error_code',
                'analysis_retryable', 'pending_sources', 'deferred_reasons', 'model_attempts',
                'analysis_retry_after', 'recovery_probes') if key in result})
            status.success(current['latest_import'], safe)
            print(json.dumps(safe))
            return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('Archive publication failed; private details withheld. Next run reconciles current outputs.',file=sys.stderr)
        print(json.dumps(failure_details(error), sort_keys=True), file=sys.stderr)
        sys.exit(1)
