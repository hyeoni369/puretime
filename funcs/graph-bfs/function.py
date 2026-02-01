#!/usr/bin/env python3
"""Graph BFS - CPU-bound benchmark from SeBS"""

import time
import json
import sys
from collections import deque

def generate_graph(n, seed=42):
    state = seed
    def lcg():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7fffffff
        return state
    
    adj = {i: [] for i in range(n)}
    for v in range(n):
        for _ in range(4):
            t = lcg() % n
            if t != v and t not in adj[v]:
                adj[v].append(t)
    return adj

def bfs(graph, start):
    dist = {start: 0}
    q = deque([start])
    visited = {start}
    while q:
        cur = q.popleft()
        for nb in graph.get(cur, []):
            if nb not in visited:
                visited.add(nb)
                dist[nb] = dist[cur] + 1
                q.append(nb)
    return dist

def main():
    size = int(sys.argv[1]) if len(sys.argv) > 1 else 1000000
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    
    start = time.perf_counter()
    graph = generate_graph(size)
    
    total = 0
    for i in range(iters):
        total += len(bfs(graph, i % size))
    
    elapsed = time.perf_counter() - start
    print(json.dumps({
        "size": size,
        "iterations": iters,
        "visited": total,
        "elapsed_ms": round(elapsed * 1000, 2)
    }))

if __name__ == "__main__":
    main()
