#!/usr/bin/env python3
import os
import json
from hashlib import sha256

def dedup_root(root):
    seen = set()
    summary = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith('_clean.jsonl'):
                path = os.path.join(dirpath, fn)
                out_lines = []
                kept = 0
                dup = 0
                with open(path, 'r', encoding='utf-8') as rf:
                    for raw in rf:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            obj = json.loads(raw)
                        except Exception:
                            continue
                        msgs = obj.get('messages')
                        if not isinstance(msgs, list):
                            continue
                        h = sha256(json.dumps(msgs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                        if h in seen:
                            dup += 1
                            continue
                        seen.add(h)
                        out_lines.append(json.dumps({'messages': msgs}, ensure_ascii=False))
                        kept += 1

                # overwrite the clean file with deduped content
                with open(path, 'w', encoding='utf-8') as wf:
                    for l in out_lines:
                        wf.write(l + '\n')

                summary[path] = {'kept': kept, 'duplicates_removed': dup}
    return summary


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--root', default='.', help='workspace root')
    args = p.parse_args()
    s = dedup_root(args.root)
    print('Dedup complete. Summary:')
    for k,v in s.items():
        print(f"{k}: kept={v['kept']} duplicates_removed={v['duplicates_removed']}")
