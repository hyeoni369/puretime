#!/usr/bin/env python3
"""UDP Sender using iperf3"""

import subprocess
import json
import os

def main():
    target_host = os.environ.get('TARGET_HOST', '165.194.27.225')
    size = os.environ.get('SIZE', '10M')

    # Run iperf3 in UDP mode
    cmd = [
        'iperf3',
        '-c', target_host,
        '-u',              # UDP mode
        '-b', '0',         # Unlimited bandwidth
        '-n', size,        # Bytes to send
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(result.stdout)
    else:
        print(json.dumps({
            'error': result.stderr,
            'returncode': result.returncode
        }))

if __name__ == "__main__":
    main()
