# vitallic-dimos

A dimOS module that adds one skill, `precise_move`, so the Go2 can take the 5 cm
steps the gradiometer scan needs.

Install it into the dimOS venv, not a fresh one:

```
VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install -e .
/root/dimensional-applications/.venv/bin/dimos list     # should show vitallic-dimos.scan
python check_install.py
```

Then:

```
dimos run vitallic-dimos.scan --robot-ip <DOG_IP>
dimos mcp call precise_move --json-args '{"x": 0.05, "y": 0.0}'
```

See [DIMOS_PORT.md](../DIMOS_PORT.md) for why this exists, the deadman timer,
and the missing `dimos[unitree]` extra on this machine.
