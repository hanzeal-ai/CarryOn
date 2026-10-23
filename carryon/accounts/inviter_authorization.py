"""One persistent invitation issuer, approved by the cloud administrator."""
import hashlib
import json
import os
import re

from carryon.paths import save_json


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def source(server):
    # A server-side recovery/configuration change supersedes remote authorization.
    return hashlib.sha256(json.dumps([
        server.account_settings.source,
        server.config.get('registrationInviteIssuerHash', ''),
        server.config.get('registrationInviteIssuerGeneration', ''),
    ]).encode()).hexdigest()


def record_path(server):
    # Recovery starts a fresh authority generation, including if the old file
    # is damaged. Old records remain available for an operator's investigation.
    return server.account_settings.directory / ('inviter-' + source(server) + '.json')


def issuer_hash(server):
    """Caller holds account_settings.locked(), also shared with account recovery."""
    directory = server.account_settings.directory
    if directory is not None:
        try:
            record = json.loads(record_path(server).read_text())
        except FileNotFoundError:
            return server.config.get('registrationInviteIssuerHash', '')
        if (not isinstance(record, dict) or record.get('version') != 1
            or record.get('source') != source(server) or not valid_hash(record.get('issuerHash'))):
            raise ValueError('云端邀请码授权记录无效，请管理员检查存储')
        return record['issuerHash']
    return server.config.get('registrationInviteIssuerHash', '')


def authorize(server, data):
    if not isinstance(data, dict) or not valid_hash(data.get('issuerHash')):
        raise ValueError('本机授权指纹无效')
    if data.get('confirm') is not True:
        raise ValueError('请确认替换邀请码生成电脑')
    with server.auth_lock, server.account_settings.locked():
        server.replace_auth(server.account_settings.effective())
        if server.auth.verify(data) != 'owner':
            raise PermissionError('只有云端管理员可以授权邀请码生成电脑')
        digest = data['issuerHash']
        if issuer_hash(server) != digest:
            directory = server.account_settings.directory
            save_json(record_path(server), {
                'version': 1, 'source': source(server), 'issuerHash': digest,
            })
        # An earlier rename may be visible even after directory fsync failed.
        # Idempotent confirmation must establish durability too.
        directory = server.account_settings.directory
        fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return {'authorized': True, 'issuerHash': digest}
