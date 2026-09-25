"""Versioned history splices. Receivers reconstruct before dropping intermediate packets."""

FIELDS = ('history', 'sideHistory')


class HistoryWire:
    def __init__(self):
        self.scope = None
        self.histories = {}

    def _select(self, packet):
        scope = (packet.get('subscription'), packet.get('threadId'), packet.get('sideThreadId'))
        if scope != self.scope or not packet.get('status', {}).get('enabled', True):
            self.histories = {}
            self.scope = scope

    def encode(self, packet):
        self._select(packet)
        result = dict(packet)
        for field in FIELDS:
            history = packet.get(field)
            if not isinstance(history, dict) or not isinstance(history.get('timeline'), list) or not history.get('historyRevision'):
                self.histories.pop(field, None)
                continue
            previous = self.histories.get(field)
            self.histories[field] = history
            if previous is None:
                continue
            before, after = previous['timeline'], history['timeline']
            splice = list_splice(before, after)
            result.pop(field)
            result[field + 'Delta'] = {
                'base': previous['historyRevision'],
                'fields': {k: v for k, v in history.items() if k != 'timeline' and (k == 'historyRevision' or k not in previous or previous[k] != v)},
                'remove': [k for k in previous if k not in history and k != 'timeline'],
                **splice}
        return result

    def decode(self, packet):
        if not isinstance(packet, dict):
            raise ValueError('Invalid history packet')
        self._select(packet)
        result = dict(packet)
        next_histories = dict(self.histories)
        for field in FIELDS:
            delta = packet.get(field + 'Delta')
            if delta is not None:
                previous = self.histories.get(field)
                if not isinstance(delta, dict) or field in packet or previous is None or delta.get('base') != previous.get('historyRevision'):
                    raise ValueError('History revision gap')
                start, count = delta.get('start'), delta.get('delete')
                items, fields = delta.get('items'), delta.get('fields')
                removed = delta.get('remove', [])
                timeline = previous.get('timeline', [])
                if (type(start) is not int or type(count) is not int or start < 0 or count < 0 or
                    start + count > len(timeline) or not isinstance(items, list) or not isinstance(fields, dict) or
                    not isinstance(fields.get('historyRevision'), str) or not isinstance(removed, list) or
                    any(not isinstance(k, str) or k in ('timeline', 'historyRevision') for k in removed)):
                    raise ValueError('Invalid history splice')
                result[field] = {**{k: v for k, v in previous.items() if k not in removed}, **fields, 'timeline': timeline[:start] + items + timeline[start+count:]}
                result.pop(field + 'Delta')
            if field in result:
                next_histories[field] = result[field]
            else:
                next_histories.pop(field, None)
        self.histories = next_histories
        return result


def list_splice(before, after):
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    end = 0
    while end < min(len(before), len(after)) - start and before[len(before)-end-1] == after[len(after)-end-1]:
        end += 1
    return {'start': start, 'delete': len(before)-start-end,
            'items': after[start:len(after)-end if end else len(after)]}
