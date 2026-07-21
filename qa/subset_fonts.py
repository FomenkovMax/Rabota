import subprocess, os, glob

LATIN = "U+0020-007E,U+00A0,U+00AB,U+00BB,U+00B7,U+2010-2027,U+202F,U+2116,U+2191,U+2193,U+21BA,U+25B2,U+2212,U+FFFD"
CYR   = "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116"

os.makedirs('src/assets/fonts/subset', exist_ok=True)
for f in sorted(glob.glob('src/assets/fonts/*.woff2')):
    name = os.path.basename(f)
    if 'cyrillic-ext' in name:  # not needed: page has no extended cyrillic
        continue
    ranges = CYR if 'cyrillic' in name else LATIN
    out = 'src/assets/fonts/subset/' + name
    subprocess.run(['pyftsubset', f, '--unicodes=' + ranges,
                    '--flavor=woff2', '--layout-features=*',
                    '--output-file=' + out], check=True)
    print(f'{name}: {os.path.getsize(f)} -> {os.path.getsize(out)}')
