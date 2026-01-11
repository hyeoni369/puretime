## **How to use**

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
