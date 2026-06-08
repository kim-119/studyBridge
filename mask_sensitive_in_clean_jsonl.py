#!/usr/bin/env python3
import os
import json
import re

SENSITIVE_RE = re.compile(r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|sk_live_[0-9a-zA-Z]{24,}|AKIA[0-9A-Z]{16}|\+?\d{2,3}[ -]?\d{3,4}[ -]?\d{4}|api[_-]?key|secret|token)", re.I)


def mask_root(root):
    summary = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith('_clean.jsonl'):
                path = os.path.join(dirpath, fn)
                changed = 0
                lines_out = []
                with open(path, 'r', encoding='utf-8') as rf:
                    for raw in rf:
                        raw = raw.rstrip('\n')
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            lines_out.append(raw)
                            continue
                        msgs = obj.get('messages')
                        if isinstance(msgs, list):
                            for m in msgs:
                                if 'content' in m and isinstance(m['content'], str):
                                    newc = SENSITIVE_RE.sub('[REDACTED]', m['content'])
                                    if newc != m['content']:
                                        changed += 1
                                        m['content'] = newc
                        lines_out.append(json.dumps(obj, ensure_ascii=False))

                if changed:
                    with open(path, 'w', encoding='utf-8') as wf:
                        for l in lines_out:
                            wf.write(l + '\n')
                summary[path] = {'masked_count': changed}
    return summary


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='.', help='workspace root')
    args = p.parse_args()
    s = mask_root(args.root)
    print('Masking complete. Summary:')
    for k,v in s.items():
        print(f"{k}: masked={v['masked_count']}")
