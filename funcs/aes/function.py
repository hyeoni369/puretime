#!/usr/bin/env python3
"""vSwarm aes (CPU victim) — gRPC handler 제거, pyaes AES-CTR 암호화만.

원본: vSwarm benchmarks/aes/python — pyaes(순수 Python AES) CTR 모드 암호화.
AES round = SubBytes(S-box 256B 룩업=L1) + ShiftRows + MixColumns + AddRoundKey(XOR),
순수 Python이라 인터프리터-bound → register/L1 (membw-bound 아님, IPC dilation 누수 없음).
원본 plaintext가 16B로 너무 짧아, size(작게=L1 유지) + rounds로 작업량 조절.
출처: vSwarm (Ustiugov et al., ASPLOS'21; github.com/vhive-serverless/vSwarm)."""
import pyaes
import sys
import time
import json

KEY = b'6368616e676520746869732070617373'  # vSwarm 기본 키 (32 bytes)


def aes_ctr_encrypt(plaintext):
    counter = pyaes.Counter(initial_value=0)
    aes = pyaes.AESModeOfOperationCTR(KEY, counter=counter)
    return aes.encrypt(plaintext)


def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 16384   # plaintext bytes (L1 유지)
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    pt = b'A' * size
    start = time.perf_counter()
    total = 0
    for _ in range(rounds):
        ct = aes_ctr_encrypt(pt)
        total += len(ct)   # dead-code guard
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({"elapsed_ms": round(elapsed_ms, 2), "size": size, "rounds": rounds, "bytes": total}))


if __name__ == "__main__":
    main()
