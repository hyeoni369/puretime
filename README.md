## **How to use**

### **0. Pre-requirements**
#### Disable NIC's offloadings
```sh
ip a  # 인터페이스 확인
ethtool -k <인터페이스>  # 인터페이스 현재 설정 확인
ethtool -K <인터페이스> tso off gso off gro off lro off  # offload disable
```

#### Enable NVMe's scheduler
```sh
cat /sys/block/<device>/queue/scheduler  # Block device의 스케줄러 확인
# none이 아니라 다른게 (대괄호로) 선택되어있으면 Pass
# 만약 [none] 이면, 다른 스케줄러 선택해줘야 함 ex) [none] mq-deadline
sudo -i
sudo echo mq-deadline > /sys/block/<device>/queue/scheduler
```

#### Setup MinIO Server (for Network Benchmark)
Network 벤치마크 테스트를 위해 별도 서버에서 MinIO를 실행해야 합니다.

##### MinIO 서버 실행
```sh
sudo systemctl enable --now docker  # 도커 자동으로 켜지게 활성화

docker run -d \
  --name minio \
  --restart unless-stopped \
  -p 9000:9000 \
  -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmincslab \
  -e MINIO_ROOT_PASSWORD=minioadmincslab \
  myminio:minio server /tmp/minio --console-address :9001
```

##### 버킷 생성 (웹 콘솔)
- http://<서버IP>:9001 접속
- minioadmin / minioadmin 로그인
- Buckets → Create Bucket → uploads 생성

### **1. Clone your new repository**

Clone your newly created repository to your local machine:

```sh
git clone https://github.com/hyeoni369/puretime.git --recursive
```

Or after clone the repo, you can update the git submodule with following commands:

```sh
git submodule update --init --recursive
```

### **2. Install dependencies**

For dependencies, it varies from distribution to distribution. You can refer to shell.nix and dockerfile for installation.

On Ubuntu, you may run `make install` or

```sh
sudo apt-get install -y --no-install-recommends \
        libelf1 libelf-dev zlib1g-dev \
        make clang llvm
```

to install dependencies.

### **3. Build the project**

To build the project, run the following command:

```sh
make build
```

### **4. Run the Project**

You can run the binary with:

```console
sudo src/puretime -v -t 10  # -v: Verbose debug output / -t(Optional): Run for specified duration
```

### **5. Check the result of tracing**

You can check the trace logs on "/var/log/puretime/trace_*.jsonl".

```console
cat /var/log/puretime/trace_*.jsonl | head -10
```

### **6. Test trace result**
#### 전체 테스트 실행 (약 90초 소요)
```console
cd ~/puretime
sudo ./tests/run_tests.sh
```

#### 기존 trace 파일 분석만 실행
```console
python3 tests/analyze_trace.py /var/log/puretime/trace_*.jsonl
```

#### JSON으로 결과 내보내기
```console
python3 tests/analyze_trace.py /var/log/puretime/trace_*.jsonl -o results.json
```