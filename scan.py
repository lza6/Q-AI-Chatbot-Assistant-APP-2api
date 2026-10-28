import re, sys, collections

data = open('libapp.so', 'rb').read()
strs = [x.decode() for x in re.findall(rb'[ -~]{4,400}', data)]

# Dart AOT: strings may be adjacent in blob; also try to find '/' starting paths
path_like = set()
for x in strs:
    if x.startswith('package:') or x.startswith('dart:') or x.startswith('org.') or x.startswith('io.'):
        continue
    if re.match(r'^/?v?\d*[a-z]*/[a-zA-Z0-9/_\-\{\}:.]*$', x) and len(x) > 4:
        path_like.add(x)

print('=== PATH-LIKE (%d) ===' % len(path_like))
for p in sorted(path_like):
    print(repr(p))
