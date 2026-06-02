#!/usr/bin/env python3
import os
import sys
import json
import re
import argparse
from hashlib import sha256

SENSITIVE_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|sk_live_[0-9a-zA-Z]{24,}|AKIA[0-9A-Z]{16}|\+?\d{2,3}[ -]?\d{3,4}[ -]?\d{4}|api[_-]?key|secret|token", re.I)


def validate_file(path, seen_hashes):
    issues = []
    line_no = 0
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line_no += 1
            s = raw.strip()
            if not s:
                issues.append((line_no, 'empty_line'))
                continue
            try:
                obj = json.loads(s)
            except Exception as e:
                issues.append((line_no, f'json_parse_error: {e}'))
                continue

            if not isinstance(obj, dict):
                issues.append((line_no, 'top_level_not_object'))
                continue

            keys = set(obj.keys())
            if keys != {'messages'}:
                issues.append((line_no, f'top_level_keys: {keys}'))
                continue

            msgs = obj.get('messages')
            if not isinstance(msgs, list):
                issues.append((line_no, 'messages_not_list'))
                continue

            roles = set()
            for m in msgs:
                if not isinstance(m, dict):
                    issues.append((line_no, 'message_not_object'))
                    continue
                mkeys = set(m.keys())
                if mkeys != {'role', 'content'}:
                    issues.append((line_no, f'message_keys: {mkeys}'))
                role = m.get('role')
                content = m.get('content')
                if role not in ('system', 'user', 'assistant'):
                    issues.append((line_no, f'invalid_role: {role}'))
                if not isinstance(content, str) or not content.strip():
                    issues.append((line_no, 'empty_content'))
                roles.add(role)

            if 'user' not in roles or 'assistant' not in roles:
                issues.append((line_no, 'missing_user_or_assistant'))

            combined = '\n'.join(m.get('content','') for m in msgs)
            if SENSITIVE_RE.search(combined):
                issues.append((line_no, 'sensitive_pattern'))

            h = sha256(json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if h in seen_hashes:
                issues.append((line_no, 'duplicate_across_files'))
            else:
                seen_hashes.add(h)

    return issues


def main(root):
    problems = {}
    seen = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith('_clean.jsonl'):
                path = os.path.join(dirpath, fn)
                issues = validate_file(path, seen)
                if issues:
                    problems[path] = issues

    if problems:
        print('Validation failed. Files with issues:')
        for p, iss in problems.items():
            print(f'- {p}:')
            for ln, msg in iss[:10]:
                print(f'  line {ln}: {msg}')
        print('\nFull report saved to validation_report.json')
        with open('validation_report.json', 'w', encoding='utf-8') as rf:
            json.dump({p: iss for p, iss in problems.items()}, rf, ensure_ascii=False, indent=2)
        sys.exit(1)
    else:
        print('All cleaned JSONL files passed validation.')
        sys.exit(0)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='.', help='workspace root')
    args = p.parse_args()
    main(args.root)
