"""Project authoritative app-server snapshots onto the desktop wire contract."""
from copy import deepcopy


def conversation(snapshot):
    state = deepcopy(dict(snapshot))
    meta = state.pop('threadMetadata', {})
    tid = state['id']
    state.update(executionBackend='carryon-owner', hostId='local', sessionId=meta.get('sessionId') or tid,
                 forkedFromId=meta.get('forkedFromId'), projectId=meta.get('projectId'), ephemeral=False, sideConversation=False,
                 createdAt=meta.get('createdAt', 0) * 1000, updatedAt=meta.get('updatedAt', 0) * 1000,
                 recencyAt=meta.get('updatedAt', 0) * 1000, mode='default', threadStartKind='default',
                 source=meta.get('source', 'vscode'), threadSource='user', historyMode='paginated',
                 modelProvider=meta.get('modelProvider', 'openai'), resumeState='resumed',
                 rolloutPath=meta.get('path'), gitInfo=meta.get('gitInfo'),
                 hasUnreadTurn=False, unreadMessageCount=0, workspaceKind='project',
                 workspaceBrowserRoot=None, projectlessOutputDirectory=None,
                 codexAppEnabledToolNames=[], environments=[], shellEnvironmentPolicy=None,
                 currentPermissions=None, latestTokenUsageInfo=state.get('latestTokenUsageInfo'))
    settings = state.get('latestThreadSettings') or {}
    state['latestCollaborationMode'] = settings.get('collaborationMode') or {
        'mode': 'default', 'settings': {'model': state.get('latestModel', ''),
        'reasoning_effort': state.get('latestReasoningEffort'), 'developer_instructions': None}}
    entities, entries = {}, []
    for turn in state['turns']:
        key = turn['turnId']
        turn.setdefault('params', {'threadId': tid, 'cwd': state['cwd'], 'input': [],
            'approvalPolicy': settings.get('approvalPolicy'), 'approvalsReviewer': settings.get('approvalsReviewer'),
            'sandboxPolicy': settings.get('sandboxPolicy'), 'model': state.get('latestModel'),
            'serviceTier': settings.get('serviceTier'), 'effort': state.get('latestReasoningEffort'),
            'summary': 'none', 'personality': None, 'outputSchema': None, 'collaborationMode': None,
            'attachments': [], 'runtimeWorkspaceRoots': []})
        turn.setdefault('turnStartedAtMs', (turn.get('startedAt') or 0) * 1000)
        turn.setdefault('hookRuns', [])
        turn.setdefault('error', None)
        turn.setdefault('diff', None)
        turn.setdefault('durationMs', None)
        entities[key] = turn
        entries.append({'key': key, 'value': key})
    state['turnHistory'] = {'kind': 'canonical', 'history': {'entitiesByKey': entities,
        'generation': 0, 'isComplete': True, 'islands': [{'id': 'tail:0', 'entries': entries,
            'olderBoundary': {'status': 'exhausted', 'boundaryId': 'tail:0:older'},
            'newerBoundary': {'status': 'exhausted', 'boundaryId': 'tail:0:newer'}}]}}
    state['turnsPagination'] = {'olderCursor': None, 'oldestLoadedTurnId': state['turns'][0]['turnId'] if state['turns'] else None,
                                'isLoadingOlder': False, 'hasLoadedOldest': True}
    return state
