# veadk-demo

An **internal employee & IT service-desk** agent ([VeADK](https://github.com/volcengine/veadk-python)),
scaffolded with `agentkit init`. It runs as the ADK API server and is delivered
as a **Feishu bot**: `agentkit deploy` builds the runtime and a Feishu proxy that
bridges the bot to it over WebSocket.

The agent (`assistant/agent.py`) answers from an internal knowledge base and can
create/track support tickets and check leave balances. Every backend is an
in-memory mock — replace each tool's body with calls to your real IT/HR systems.

## Run it locally

```bash
pip install -r requirements.txt
cp .env.example .env        # set your Volcengine AK/SK
python main.py              # serves the ADK API on http://0.0.0.0:8000
```

Probe it: `curl localhost:8000/list-apps`.

## Deploy it (with the Feishu bot)

```bash
export FEISHU_APP_ID=... FEISHU_APP_SECRET=...
agentkit deploy
```

`im.feishu` is already enabled in `.agentkit/agentkit.yaml`, so `agentkit deploy`
also ships the Feishu proxy — no flags needed. See the docs for creating the
Feishu app and granting bot permissions.

## Next steps

- Replace the mock tools in `assistant/agent.py` with your real ITSM/HR APIs.
- Tune the `instruction` for your company's tone and policies.
