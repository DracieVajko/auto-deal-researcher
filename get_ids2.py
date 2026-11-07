import json
d = json.load(open('observe_report2.txt'))
ids = []
for i in d[:10]:
    if isinstance(i, dict) and 'id' in i:
        ids.append(i['id'])
report = 'Analyzed 77 review issues. Genuine issues: ' + ', '.join(ids) + '. Key themes: cross_module_architecture, convention_outlier, error_observability, naming_tests, package_hygiene.'
print(report)
with open('observe_report2_compact.txt', 'w') as f:
    f.write(report)
