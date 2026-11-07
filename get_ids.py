import json
d = json.load(open('observe_report.txt'))
ids = []
for i in d['issues'][:10]:
    ids.append(i['hash'])
print(' '.join(ids))
