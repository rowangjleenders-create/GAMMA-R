# Open GAMMA-R in another workspace

## Option A — Same computer, new Grok / Cursor workspace
1. Choose **Open folder** (or set workspace root) to:
   `/workspace/GAMMA-R`
2. Tell the other assistant: *“This is GAMMA-R. Read OPEN_IN_WORKSPACE.md and README.md. Co-pilot is E-ve. Paper-first.”*

## Option B — Download → other machine / other Grok
1. Take `GAMMA-R-workspace.tar.gz`
2. Unpack: `tar -xzf GAMMA-R-workspace.tar.gz`
3. Open the resulting `GAMMA-R` folder as the workspace root
4. Same prompt as above

## First run in the new workspace
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m momentum_bot serve --host 127.0.0.1 --port 8000

cd mobile && npm install && npx expo start
```

## Notes
- Secrets are not included; add API keys via env / SecureStore
- Live trading stays locked unless you enable it
- Persona: **E-ve**
