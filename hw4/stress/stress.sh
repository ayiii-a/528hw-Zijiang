#!/bin/bash
# Step 8 stress test. Run it on the client VM, in the folder that holds http-client:
#   bash stress.sh 34.136.109.218
# Runs 1, 2, 3 and 4 concurrent clients for 3 minutes each, with 1 idle minute before
# every phase, prints the status codes each phase got, and writes the phase times to phases.txt.
set -u
SERVER=${1:?usage: bash stress.sh SERVER_IP}
: > phases.txt
for n in 1 2 3 4; do
    sleep 60
    start=$(date +%s)
    for i in $(seq "$n"); do
        timeout 180 ./http-client -d "$SERVER" -p 80 -b 528-zz-hw2 -w pages -i 11999 \
            -n 1000000 -r "$n$i" -v > "out_${n}_$i.txt" 2>&1 &
    done
    wait
    echo "$n $start $(date +%s)" >> phases.txt
    echo "== $n concurrent client(s), $(date -u -d @"$start" +%T) - $(date -u +%T) UTC"
    # the status line is the first "NNN ..." line after each "Requesting" line;
    # a request with no status line before the next one got no response
    awk 'FNR == 1 && pending { cut++; pending = 0 }
         /^Requesting/ { if (pending) noresp++; pending = 1; next }
         pending && /^[0-9][0-9][0-9] / { status[$1]++; total++; pending = 0 }
         END { if (pending) cut++
               for (s in status) printf "   %s: %d\n", s, status[s]
               printf "   answered: %d (%.1f req/s)   no response: %d   cut off by the 3-minute limit: %d\n",
                      total, total / 180, noresp, cut }' out_${n}_*.txt
done
