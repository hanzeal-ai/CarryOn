"""Per-binding request identities; native sessions and execution remain shared."""
import hashlib
import re
from urllib.parse import urlsplit, parse_qs
from .api import dispatch
from .errors import BridgeError


def request_key(binding, value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',value):
        raise ValueError('requestId 必须为 8–100 位字母、数字、横线或下划线')
    return hashlib.sha256((binding+'\0'+value).encode()).hexdigest()


def project_job(job):
    return {**{k:v for k,v in job.items() if k not in ('sourceBinding','sourceRequestId')},
            'id':job['sourceRequestId']}


def project_packet(packet,binding):
    if binding is None or 'jobs' not in packet:return packet
    return {**packet,'jobs':[project_job(j) for j in packet['jobs'] if j.get('sourceBinding')==binding]}


def scoped_dispatch(bridge,method,target,data,control,binding,authorize=None):
    if binding is None:return dispatch(bridge,method,target,data,remote=True,control=control)
    if authorize:authorize()
    parsed=urlsplit(target)
    # Validate the original route and permission before handling scoped jobs.
    if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/api/'):
        raise ValueError('Invalid API path')
    if method not in ('GET','POST'):raise ValueError('Invalid method')
    if (parsed.path in ('/api/projects','/api/activity','/api/notifications','/api/notifications/read','/api/notifications/preferences') or re.fullmatch(r'/api/projects/[0-9a-f]{64}/threads',parsed.path)):
        if not hasattr(bridge,'workspace'):raise BridgeError('工作区功能尚未启用，请升级本机服务',503)
        return bridge.workspace.dispatch('binding:'+binding,method,parsed.path,data,parse_qs(parsed.query))
    if method=='POST' and not control:raise BridgeError('本机仅授权云端读取',403)
    path=parsed.path
    if path=='/api/jobs' and method=='GET':
        bridge.require()
        jobs=[j for j in bridge.journal.list() if j.get('sourceBinding')==binding][:100]
        return 200,{'jobs':[project_job(bridge.refresh_job(j['id'])) for j in jobs]}
    if re.fullmatch(r'/api/jobs/[^/]+(?:/acknowledge)?',path):
        original=path.split('/')[3];internal=request_key(binding,original)
        bridge.require()
        job=bridge.journal.get(internal)
        if not job or job.get('sourceBinding')!=binding:raise BridgeError('请求不存在',404)
        target=target.replace('/api/jobs/'+original,'/api/jobs/'+internal,1)
    source=None
    if method=='POST' and (path=='/api/threads' or re.fullmatch(r'/api/threads/[^/]+/(messages|operations|compose)',path)):
        if not isinstance(data,dict):raise ValueError('请求体必须是 JSON 对象')
        original=data.get('requestId')
        data={**data,'requestId':request_key(binding,original)}
        source={'sourceBinding':binding,'sourceRequestId':original}
    status,result=dispatch(bridge,method,target,data,remote=True,control=control,source=source,authorize=authorize)
    if isinstance(result,dict) and result.get('sourceBinding')==binding:result=project_job(result)
    return status,result
