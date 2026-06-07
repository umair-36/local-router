# Minimal setup
```bash
cd minimal

chmod +x *.sh

./setup_server.sh \
  "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  "qwen2.5-0.5b-instruct"

./run_server.sh

./setup-nginx.sh
```

Test Locally:
```bash
curl.exe -s http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d '{
    "model": "qwen2.5-0.5b-instruct",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 64
  }'
  ```

Test Externally:
```cmd
curl.exe -s http://XXX.XXX.XXX.XXX/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"qwen2.5-0.5b-instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}],\"max_tokens\":64}"
```
