import json, subprocess, os, sys
ROOT = r"C:\Users\DracieVajko\Downloads\PC_Commands\AI\PersonalAIDealSearcher"
os.chdir(ROOT)
p=json.load(open('.desloppify/plan.json'))
clusters=json.load(open('manual_clusters.json'))
bad_paths=['src/cli/commands/run.py','src/storage/models.py','src/models/deal.py','src/llm/json_utils.py']
for name,c in p['clusters'].items():
    if c.get('auto'): continue
    for i,s in enumerate(c.get('action_steps',[]),1):
        d=s.get('detail','')
        orig=d
        for bp in bad_paths:
            d=d.replace(bp,'')
        # clean double spaces
        while '  ' in d: d=d.replace('  ',' ')
        if d!=orig:
            # find effort/refs from manual_clusters? use current
            effort=s.get('effort','medium')
            refs=s.get('issue_refs',[]) or clusters[name]['issue_ids']
            cmd=[sys.executable,'-m','desloppify','plan','cluster','update',name,
                 '--update-step',str(i),'--detail',d,'--effort',effort,'--issue-refs']+refs
            r=subprocess.run(cmd,capture_output=True,text=True,cwd=ROOT)
            print(name,i,'rc',r.returncode)
            if r.returncode!=0:
                print(r.stderr[-300:])
print('DONE')
