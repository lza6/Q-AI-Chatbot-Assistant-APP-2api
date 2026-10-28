import re

data = open('libapp.so', 'rb').read()
strs = [x.decode() for x in re.findall(rb'[ -~]{3,400}', data)]
out = []
seen = set()
for x in strs:
    if x.startswith('package:') or x.startswith('dart:') or x.startswith('assets/') or x.startswith('flutter/'):
        continue
    if x in seen:
        continue
    seen.add(x)
    out.append(x)
open('strings.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('total', len(out))
