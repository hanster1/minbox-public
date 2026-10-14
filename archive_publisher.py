"""Owner-scoped incremental work Docs publisher. Raw archives remain read-only."""
import json
from archive_corrections import CorrectionLedger, parse_corrections
from archive_incremental import AnalysisFailure, IncrementalArchive, hard_excluded


def _url(doc):
    return 'https://docs.google.com/document/d/' + doc


def run(config, snapshot, client, analyzer):
    owner, docs = config['owner'], config['documents']
    policy = config.get('analysis_policy','archive-work-v1')
    if set(docs) != {'guide','messages','looms','knowledge','corrections','status'} or len(set(docs.values())) != 6:
        raise ValueError('publisher input and output identities must be distinct')
    sources = snapshot['sources']
    core_sources = [{k:s[k] for k in ('source_id','revision','owner','conversation_id','timestamp','text','kind','origin_ids')} for s in sources]
    threads = {}
    for source in sorted(core_sources, key=lambda s:(s['timestamp'],s['source_id'])):
        if source['kind'] == 'message':
            thread = threads.setdefault(source['conversation_id'], [])
            source['context'] = [] if config.get('seed_revisions',{}).get(source['source_id']) == source['revision'] else thread[-3:]
            thread.append(source['source_id'])
    if any(s['owner'] != owner or s['conversation_id'] not in config['conversations'] or s['timestamp'][:10] < config['start_date'] for s in sources):
        raise ValueError('snapshot differs from authorized owner/thread scope')
    if len({s['friendly_id'] for s in sources}) != len(sources):
        raise ValueError('ambiguous message aliases')
    cache = IncrementalArchive(config['analysis_path'], scope={'owner':owner,
        'conversation_ids':config['conversations'],'start_date':config['start_date']},
        max_model_calls=config.get('max_model_calls',1),
        recovery_enabled=config.get('analysis_recovery',True),
        operator_paused=config.get('analysis_paused',False))
    ledger = CorrectionLedger(config['correction_path'])
    try:
        messages = [s for s in sources if s['kind'] == 'message']
        core_messages = [s for s in core_sources if s['kind'] == 'message']
        core_looms = [s for s in core_sources if s['kind'] == 'loom']
        looms = [s for s in sources if s['kind'] == 'loom']
        # Seed only exact reviewed revisions; new/revised content must be analyzed.
        seeds = config.get('seed_decisions', [])
        seed_sources = [s for s in core_sources if config.get('seed_revisions', {}).get(s['source_id']) == s['revision']]
        seed_ids = {s['source_id'] for s in seed_sources}
        if seed_sources:
            cache.seed(owner, seed_sources, [d for d in seeds if d['source_id'] in seed_ids],policy=policy)
        input_doc = client.read(docs['corrections'])
        correction_text = input_doc['text'].split('Corrections begin below.', 1)[-1]
        correction_records = parse_corrections(correction_text)
        initial_messages = cache.records(owner, core_messages,policy=policy)
        initial_looms = cache.records(owner, core_looms,policy=policy)
        registry = {s['friendly_id']: {'owner':owner,'label':(initial_messages if s['kind']=='message' else initial_looms)[s['source_id']]['label'],
            'source_revision':s['revision'],'provenance':s['source_id']} for s in sources}
        initial_corrections = ledger.ingest(owner, correction_records, registry)
        active_targets = {json.loads(row['payload']).get('target') for row in ledger.history(owner)
                          if row['status']=='applied' and json.loads(row['payload']).get('action')!='undo'}
        # Applied corrections alone can gate a source; cached model labels only
        # guide dependencies. Spam stays active until its explicit undo.
        spam_targets = {json.loads(row['payload']).get('target') for row in ledger.history(owner)
                        if row['status']=='applied' and json.loads(row['payload']).get('action')=='spam'}
        overrides = {s['source_id']:initial_corrections['effective_labels'][s['friendly_id']] for s in messages
                     if s['friendly_id'] in active_targets}
        overrides.update({s['source_id']: 'spam' for s in messages if s['friendly_id'] in spam_targets})
        attempts_before = cache.state(owner)['model_attempts']
        try:
            message_run = cache.analyze(owner, core_messages, analyzer, policy=policy,labels=overrides,source_overrides=overrides)
        except AnalysisFailure as error:
            message_run = error.result
        except Exception:
            message_run = {'analysis_failed': True, 'analysis_state': 'needs_attention',
                           'error_code': 'analysis_failed', 'model_calls': 0, 'model_attempts': 0,
                           'pending_sources': len(core_messages), 'retryable': False}
        message_records = cache.records(owner, core_messages,policy=policy,labels=overrides,source_overrides=overrides)
        for source in messages:
            registry[source['friendly_id']]['label'] = message_records[source['source_id']]['label']
        corrections = ledger.ingest(owner, correction_records, registry)
        labels = {s['source_id']: corrections['effective_labels'][s['friendly_id']] for s in sources}
        for s in sources:
            if hard_excluded(s['text']) or s['friendly_id'] in spam_targets:
                labels[s['source_id']] = 'spam'
        loom_overrides = {s['source_id']: labels[s['source_id']] for s in looms
                          if s['friendly_id'] in active_targets}
        # Durable attempts include failures and interrupted adapter completions.
        message_attempts = cache.state(owner)['model_attempts'] - attempts_before
        remaining_calls = max(0, cache.max_model_calls - message_attempts)
        try:
            loom_run = cache.analyze(owner, core_looms, analyzer,policy=policy,labels=labels,
                                     source_overrides=loom_overrides,max_calls=remaining_calls)
        except AnalysisFailure as error:
            loom_run = error.result
        except Exception:
            loom_run = {'analysis_failed': True, 'analysis_state': 'needs_attention',
                        'error_code': 'analysis_failed', 'model_calls': 0, 'model_attempts': 0,
                        'pending_sources': len(core_looms), 'retryable': False}
        loom_records = cache.records(owner, core_looms,policy=policy,labels=labels,source_overrides=loom_overrides)
        for source in looms:
            registry[source['friendly_id']]['label'] = loom_records[source['source_id']]['label']
        final_corrections = ledger.ingest(owner, correction_records, registry)
        correction_changes = initial_corrections['changed'] + corrections['changed'] + final_corrections['changed']
        corrections = final_corrections
        labels = {s['source_id']: corrections['effective_labels'][s['friendly_id']] for s in sources}
        for source in sources:
            if hard_excluded(source['text']) or source['friendly_id'] in spam_targets:
                labels[source['source_id']] = 'spam'
        records = {**message_records, **loom_records}
        visible_messages = [s for s in messages if labels[s['source_id']] == 'work']
        visible_looms = [s for s in looms if labels[s['source_id']] == 'work' and
                         any(labels.get(origin) == 'work' for origin in s['origin_ids'])]
        visible = {s['source_id']:s for s in visible_messages + visible_looms}
        loom_gaps = [g for g in snapshot.get('loom_gaps',[]) if any(labels.get(sid)=='work' for sid in g['origin_ids'])]
        coverage = ['Scope: selected work messages in configured threads; private/personal/uncertain excluded.',
                    'Latest captured scoped message: ' + str(snapshot['latest_scoped_message']),
                    'Attachment bytes unavailable. Capture completeness is not established.',
                    'Work-linked Looms without a saved transcript: '+str(len(loom_gaps)),
                    'Scoped non-text events or unavailable/retracted bodies omitted: '+str(len(snapshot.get('message_gaps', [])))]
        bodies = {'messages': ['Captured Work Messages — Current', 'Owner: '+owner, *coverage, ''],
                  'looms': ['Work Loom Transcripts — Current', 'Owner: '+owner, *coverage, ''],
                  'knowledge': ['Reusable Work Knowledge — Current', 'Orientation only; verify original cited sources. Earlier plans are not proof of current completion.',
                                *coverage, '']}
        for s in visible_messages:
            bodies['messages'].extend([s['friendly_id']+' | '+s['timestamp']+' | '+s['sender'],
                'Revision: '+s['revision'], 'Source: '+s['source_id'], s['text'], ''])
        for gap in loom_gaps:
            bodies['looms'].extend(['Transcript unavailable: https://www.loom.com/share/'+gap['video_id'], 'Capture status: '+gap['status'], ''])
        for s in visible_looms:
            bodies['looms'].extend([s['friendly_id'], 'Revision: '+s['revision'], 'Source: '+s['source_url'],
                'Origin messages: '+', '.join(visible[x]['friendly_id'] for x in s['origin_ids'] if x in visible)])
            for phrase in s.get('phrases', []):
                stamp = float(phrase['ts'])
                bodies['looms'].append(f"{int(stamp)//60:02d}:{stamp%60:06.3f} — {phrase['value']}")
            if not s.get('phrases'):
                bodies['looms'].append(s['text'])
            bodies['looms'].append('')
        # Reviewed cross-source facts survive only while every dependency remains visible/current.
        for fact in config.get('reviewed_facts', []):
            if all(sid in visible and visible[sid]['revision'] == revision for sid, revision in fact['dependencies'].items()):
                bodies['knowledge'].extend([fact['kind']+': '+fact['statement'],
                    'Source dates: '+', '.join(sorted({visible[sid]['timestamp'] for sid in fact['dependencies']})),
                    'Sources: '+', '.join(visible[sid]['friendly_id'] for sid in fact['dependencies']), ''])
        for sid,s in visible.items():
            for fact in records[sid]['facts']:
                bodies['knowledge'].extend([fact['kind']+': '+fact['statement'],
                    'Source: '+s['friendly_id']+' | '+_url(docs['looms'] if s['kind']=='loom' else docs['messages']), ''])
        bodies['knowledge'].extend(['Owner context (not imported message evidence):', config.get('owner_context',''),
            'Primary messages: '+_url(docs['messages']), 'Primary Looms: '+_url(docs['looms'])])
        bodies['guide'] = ['Work Archive — Current', 'Owner: '+owner,*coverage,
            'Use primary messages and timestamped Looms for citations. Reusable notes are orientation.',
            'Classifications are automatic. No routine review queue is required.',
            'To correct a message, tell your AI assistant its message ID and desired work/personal/spam label.',
            'Ask it to append to the Corrections Doc using that Doc format. Saved means recorded; status confirms applied.',
            'Messages: '+_url(docs['messages']), 'Looms: '+_url(docs['looms']),
            'Knowledge: '+_url(docs['knowledge']), 'Corrections: '+_url(docs['corrections']),
            'Publisher status: '+_url(docs['status'])]
        writes = 0
        # Withdrawal first: no stale derived personal material after the final acknowledgement.
        for key in ['knowledge','looms','messages','guide']:
            writes += bool(client.replace(docs[key], '\n'.join(bodies[key])))
        if client.read(docs['corrections'])['revision'] != input_doc['revision']:
            raise RuntimeError('corrections changed during publication; latest state will be reconciled next run')
        status = ['Work Archive — Publisher Status','Owner: '+owner,
            'Outputs verified against correction revision: '+input_doc['revision'],
            f"Published work messages: {len(visible_messages)}; work Looms: {len(visible_looms)}",
            'Last imported change in scoped sources: '+str(max((s.get('imported_at',s.get('captured_at','')) for s in sources),default='unknown')),
            'Import freshness is not proof of complete phone capture.',
            'New/changed sources are analyzed once; cached classifications and notes are reused.',
            'Deferred source analyses: '+str(sum(len(r.get('deferred',[])) for r in (message_run,loom_run))),
            'Reported token totals for this publisher: '+str(cache.state(owner)['input_tokens']+cache.state(owner)['output_tokens']),
            'Analysis state: '+('failed/paused; new unresolved sources remain unpublished' if message_run.get('analysis_failed') or loom_run.get('analysis_failed') or message_run.get('paused') or loom_run.get('paused') else 'pending/partial; deferred sources remain unpublished' if message_run.get('deferred') or loom_run.get('deferred') else 'ready'),
            'Original archive records remain unchanged.']
        for c in corrections['statuses']:
            reason = c['reason']
            if c['source_context'].get('provenance') and labels.get(c['source_context']['provenance']) == 'spam' and c['status']=='applied':
                reason = (reason+'; ' if reason else '')+'security or active spam exclusion still wins; undo the spam correction to remove that exclusion'
            status.append(f"{c['correction_id']} revision {c['revision']}: {c['status']} {reason}")
        writes += bool(client.replace(docs['status'],'\n'.join(status)))
        analysis_runs = (message_run, loom_run)
        priority = {'ready':0, 'pending':1, 'retry_wait':2, 'manual_hold':3, 'exhausted':4, 'needs_attention':5}
        degraded = max(analysis_runs, key=lambda item:priority[item['analysis_state']])
        deferred_reasons = {}
        for item in analysis_runs:
            for reason, count in item.get('deferred_reasons',{}).items():
                deferred_reasons[reason] = deferred_reasons.get(reason,0) + count
        return {'writes':writes,'message_analysis':message_run,'loom_analysis':loom_run,
                'work_messages':len(visible_messages),'work_looms':len(visible_looms),
                'correction_changes':correction_changes,
                'analysis_state':degraded['analysis_state'],
                'analysis_error_code':degraded.get('error_code',''),
                'analysis_retryable':degraded.get('retryable',False),
                'pending_sources':sum(item.get('pending_sources',0) for item in analysis_runs),
                'deferred_reasons':deferred_reasons,
                'model_attempts':sum(item.get('model_attempts',0) for item in analysis_runs),
                'analysis_retry_after':max(item.get('retry_after',0) for item in analysis_runs),
                'recovery_probes':cache.state(owner)['recovery_probes']}
    finally:
        ledger.close()
        cache.close()
