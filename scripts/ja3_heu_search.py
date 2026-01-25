"""
Heuristic JA3 search script
- Tries small permutations of the cipher suite order (swaps in top-K) combined with adding candidate extensions
- Stops when target JA3 digest matched and writes /tmp/ja3_heu_match.json
"""
import itertools
import json
import sys
from tls_client import Session

TARGET = "1a35fa7b8bc1f11a7ed5e4f1cda22c86"
CLIENTS = ["chrome_120", "chrome_143", "chrome_116", "chrome_110"]
CANDIDATE_POOL = ["35466","65281","65037","17513","47802","2570","32768","65282"]
MAX_ATTEMPTS = 5000
MAX_ADD = 2
PROGRESS_EVERY = 50
TOP_K = 6

attempts = 0
found = None

print(f"Starting heuristic JA3 search (max attempts={MAX_ATTEMPTS})")
for client in CLIENTS:
    print(f"\n== client: {client} ==")
    s_base = Session(client_identifier=client, random_tls_extension_order=False)
    try:
        base = s_base.get('https://tools.scrapfly.io/api/fp/ja3').json()
    except Exception as e:
        print('base fetch error:', e)
        continue
    base_digest = base.get('ja3_digest')
    base_ja3 = base.get('ja3')
    print('base_digest:', base_digest)
    print('base_ja3:', base_ja3)
    if base_digest == TARGET:
        print('Base matches target for client', client)
        found = (client, base_ja3, base)
        break

    parts = base_ja3.split(',')
    if len(parts) != 5:
        print('unexpected ja3 format, skipping')
        continue
    ver, ciphers, exts, curves, points = parts
    ciphers_list = ciphers.split('-') if ciphers else []
    ext_list = exts.split('-') if exts else []

    # generate swap pairs within top K
    K = min(TOP_K, len(ciphers_list))
    swap_pairs = [(i,j) for i in range(K) for j in range(i+1,K)]
    # also include identity (no swap)
    swap_pairs = [None] + swap_pairs

    missing = [e for e in CANDIDATE_POOL if e not in ext_list]
    print('missing candidate exts:', missing)

    for swap in swap_pairs:
        # make new cipher list copy
        cpy = list(ciphers_list)
        if swap:
            i,j = swap
            cpy[i], cpy[j] = cpy[j], cpy[i]
        # try additions up to MAX_ADD
        for rcount in range(0, min(MAX_ADD, len(missing)) + 1):
            for add_set in itertools.combinations(missing, rcount):
                attempts += 1
                cand_exts = ext_list + list(add_set)
                cand = ','.join([ver, '-'.join(cpy), '-'.join(cand_exts), curves, points])
                try:
                    s = Session(client_identifier=client, ja3_string=cand, random_tls_extension_order=False)
                    jr = s.get('https://tools.scrapfly.io/api/fp/ja3').json()
                except Exception as e:
                    jr = {'error': str(e)}
                digest = jr.get('ja3_digest')
                if attempts % PROGRESS_EVERY == 0:
                    print('attempts', attempts, 'last_digest', digest)
                if digest == TARGET:
                    found = (client, cand, jr)
                    break
                if attempts >= MAX_ATTEMPTS:
                    break
            if found or attempts >= MAX_ATTEMPTS:
                break
        if found or attempts >= MAX_ATTEMPTS:
            break
    if found or attempts >= MAX_ATTEMPTS:
        break

print('\n--- finished heuristic search ---')
print('total attempts:', attempts)
if found:
    client, cand_ja3, jr = found
    print('FOUND MATCH! client:', client)
    print('ja3:', cand_ja3)
    print('server response:', json.dumps(jr, indent=2)[:2000])
    s_test = Session(client_identifier=client, ja3_string=cand_ja3, h2_settings={"1":65536, "2":0, "4":6291456, "6":262144}, h2_settings_order=["1","2","4","6"], random_tls_extension_order=False)
    ak = s_test.get('https://tools.scrapfly.io/api/fp/akamai').json()
    print('\nakamai:', json.dumps(ak, indent=2))
    out = {'client': client, 'ja3': cand_ja3, 'ja3_server': jr, 'akamai': ak}
    with open('/tmp/ja3_heu_match.json', 'w') as fh:
        fh.write(json.dumps(out, indent=2))
    print('\nSaved match to /tmp/ja3_heu_match.json')
    sys.exit(0)
else:
    print('No match found within attempt limit')
    sys.exit(2)
