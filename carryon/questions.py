"""Codex async-message questions; replies are ordinary non-blocking user inputs."""
import json

OPEN = '<send_user_message_question_reply>'
CLOSE = '</send_user_message_question_reply>'


def reply_answers(value):
    if not isinstance(value, str):
        return []
    value = value.strip()
    if not (value.startswith(OPEN) and value.endswith(CLOSE)):
        return []
    try:
        records = json.loads(value[len(OPEN):-len(CLOSE)])
    except ValueError:
        return []
    records = records if isinstance(records, list) else [records]
    return records if records and all(isinstance(r, dict) and all(isinstance(r.get(k), str) for k in ('questionItemId', 'question', 'answer')) for r in records) else []


def project_questions(entries):
    answers = {}
    for item in entries:
        if item['type'] not in ('userMessage', 'steeringUserMessage'):
            continue
        replies = reply_answers(item.get('text'))
        if not replies:
            continue
        if item['type'] == 'userMessage' or item.get('status') == 'accepted':
            answers.update((r['questionItemId'], r['answer']) for r in replies)
        item['text'] = '\n\n'.join(r['question'] + '\n' + r['answer'] for r in replies)
    active = {i['turnId']: i.get('status') == 'inProgress' for i in entries if i['type'] == 'turn'}
    for item in entries:
        data = item.get('data', {})
        if item['type'] != 'agentMessage' or data.get('delivery') != 'async':
            continue
        native_id = item.get('nativeId')
        if not isinstance(native_id, str):
            continue
        questions = data.get('questions')
        structured = isinstance(questions, list) and bool(questions)
        questions = questions if structured else [{'title': item.get('text', ''), 'options': []}]
        projected = []
        for index, question in enumerate(questions):
            if not isinstance(question, dict) or not isinstance(question.get('title'), str):
                continue
            identifier = json.dumps(['request_user_input_async', native_id, index], ensure_ascii=False, separators=(',', ':')) if structured else native_id
            options = question.get('options', [])
            projected.append({'id': identifier, 'title': question['title'],
                              'options': [o for o in options if isinstance(o, str)] if isinstance(options, list) else [],
                              'answer': answers.get(identifier), 'active': active.get(item['turnId'], False)})
        item['asyncQuestions'] = projected


def pending_questions(native_turns):
    """Reuse the public question projection for actionable workspace notifications."""
    from .timeline import project_item
    entries = []
    for turn in native_turns:
        entries.append({'type': 'turn', 'turnId': turn.get('turnId'), 'status': turn.get('status')})
        for index, item in enumerate(turn.get('items', [])):
            if item.get('type') in ('userMessage', 'steeringUserMessage') or (
                item.get('type') == 'agentMessage' and item.get('delivery') == 'async'
            ):
                entries.append(project_item(item, turn, index))
    project_questions(entries)
    return [dict(question, turnId=item['turnId'], itemId=item.get('nativeId'))
            for item in entries for question in item.get('asyncQuestions', [])
            if question['active'] and question['answer'] is None]
