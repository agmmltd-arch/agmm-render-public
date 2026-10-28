#!/usr/bin/env python3
"""Authenticated encryption for private writer requests and responses.

Candidate only; installation and live writer cutover are separate decisions.
"""
import hashlib
import hmac
import os
import subprocess

MAGIC = b'AGW1'


def _key(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), b'AGMM-writer-auth:' + salt, 200000, 32)


def crypt(data, password, decrypt=False):
    if not password or '\n' in password:
        raise ValueError('writer encryption password missing or invalid')
    if decrypt:
        if len(data) < 4 + 16 + 16 + 32 or data[:4] != MAGIC:
            raise ValueError('invalid encrypted writer payload')
        salt, body, supplied = data[4:20], data[20:-32], data[-32:]
        expected = hmac.new(_key(password, salt), data[:-32], hashlib.sha256).digest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError('writer payload authentication failed')
    else:
        salt, body = os.urandom(16), data
    env = dict(os.environ, AGMM_WRITER_PASS=password)
    args = ['openssl', 'enc', '-aes-256-cbc', '-pbkdf2', '-iter', '200000',
            '-pass', 'env:AGMM_WRITER_PASS']
    if decrypt:
        args.append('-d')
    output = subprocess.run(args, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, check=True).stdout
    if decrypt:
        return output
    envelope = MAGIC + salt + output
    return envelope + hmac.new(_key(password, salt), envelope, hashlib.sha256).digest()
