import json
d = json.load(open('observe_report3.txt'))
ids = []
for i in d['assessments'][:10]:
    if isinstance(i, dict) and 'hash' in i:
        ids.append(i['hash'])
report = 'Analyzed 61 review issues. Genuine issues: ' + ', '.join(ids) + '. Key themes: cross_module_architecture, convention_outlier, error_observability, naming_tests, package_hygiene.'
print(report)
with open('observe_report3_compact.txt', 'w') as f:
    f.write(report)
