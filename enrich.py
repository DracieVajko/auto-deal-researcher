import json, subprocess, os, sys

ROOT = r"C:\Users\DracieVajko\Downloads\PC_Commands\AI\PersonalAIDealSearcher"
os.chdir(ROOT)

clusters = json.load(open('manual_clusters.json'))
issues = {i['id']: i for i in json.load(open('all_issues.json'))['by_file']['.']}

def exists(p):
    return os.path.exists(os.path.join(ROOT, p))

def cluster_files(cname):
    files = []
    seen = set()
    for iid in clusters[cname]['issue_ids']:
        iss = issues.get(iid)
        if not iss: continue
        for f in iss['detail'].get('related_files', []):
            if f not in seen and exists(f):
                seen.add(f); files.append(f)
    return files

def cluster_suggestions(cname):
    sugs = []
    seen=set()
    for iid in clusters[cname]['issue_ids']:
        iss = issues.get(iid)
        if not iss: continue
        s = iss['detail'].get('suggestion','')
        if s and s not in seen:
            seen.add(s); sugs.append(s)
    return sugs

for cname, cdata in clusters.items():
    files = cluster_files(cname)
    sugs = cluster_suggestions(cname)
    for step in cdata['steps']:
        n = step['i']
        detail = step['detail'] or ''
        effort = step['effort'] or 'medium'
        refs = step['refs'] if step['refs'] else cdata['issue_ids']
        # Detect if detail already contains an existing file path
        has_path = any(exists(tok.strip('.,:;')) for tok in detail.replace('`','').split() if '/' in tok or '\\' in tok)
        # generic step detection
        generic = detail.strip().startswith('Apply the suggested changes')
        if generic or not has_path:
            # build aggregated detail
            file_part = ', '.join(files[:8]) if files else ''
            sug_part = '; '.join(sugs[:4])
            new_detail = f"In {file_part}: {detail} Suggestions: {sug_part}"
            if len(new_detail) < 80:
                new_detail += " " + " ".join(sugs)
            detail = new_detail
        # ensure refs list
        cmd = [sys.executable, '-m', 'desloppify', 'plan', 'cluster', 'update', cname,
               '--update-step', str(n),
               '--detail', detail,
               '--effort', effort,
               '--issue-refs'] + refs
        print('RUN:', cname, n, len(detail), len(refs))
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            print('ERR', cname, n, r.returncode)
            print(r.stdout[-500:])
            print(r.stderr[-500:])
        else:
            print('OK', cname, n)
print('DONE')
