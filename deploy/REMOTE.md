# Hosting the Grimoire on your own box (Cloudflare Tunnel)

Run the Grimoire as a service on the same VPS that already serves
`n8n.aquryu.space`, reachable from anywhere by any MCP-capable agent (Gemini CLI,
Codex, another Claude), with no ports opened on the host.

What you end up with:

| Subdomain | Serves | Who uses it | Gate |
|---|---|---|---|
| `grimoire.aquryu.space` | dashboard + REST API | you, in a browser | Cloudflare Access (login) |
| `mcp.aquryu.space/mcp` | the MCP gateway (HTTP) | your agents | bearer token (+ optional Access service token) |

The stack (`deploy/docker-compose.yml`): `grimoire` (dashboard/API), `mcp` (the
gateway over HTTP), `ollama` (CPU embeddings), and `cloudflared` (the tunnel). They
share one SQLite store on a Docker volume. Completions use your Groq key first and
fall back to Ollama; embeddings run on Ollama CPU (the `nomic-embed-text` model is
small, no GPU needed).

Everything here is free: it reuses the server you already pay for, Groq's free tier,
and Cloudflare's free tunnel/Access.

---

## Prerequisites

- `aquryu.space` is managed in Cloudflare (same as your n8n setup).
- Docker + Docker Compose on the box.
- Your Groq API key.

---

## Step 1 — Create the Cloudflare Tunnel (in the Cloudflare dashboard)

1. Go to **Cloudflare dashboard -> Zero Trust -> Networks -> Tunnels**.
2. **Create a tunnel** -> connector type **Cloudflared** -> name it `grimoire`.
3. On the install screen, **copy the tunnel token** (the long string after
   `--token` in the shown command). You do NOT run that command yourself, the
   `cloudflared` container will use the token. Paste it into `deploy/.env` later as
   `CLOUDFLARE_TUNNEL_TOKEN`.
4. Click through to **Public Hostnames** and add two:

   | Subdomain | Domain | Type | URL |
   |---|---|---|---|
   | `grimoire` | `aquryu.space` | HTTP | `http://grimoire:8731` |
   | `mcp` | `aquryu.space` | HTTP | `http://mcp:8730` |

   Those URLs use the Docker **service names** because `cloudflared` runs inside the
   same compose network. Cloudflare auto-creates the DNS records for you.

Leave the dashboard open, you will gate access in Step 3.

---

## Step 2 — Bring it up on the box

```bash
git clone https://github.com/adxoxo/grimoire.git
cd grimoire/deploy
cp .env.example .env
```

Edit `deploy/.env`:

```ini
GRIMOIRE_GROQ_API_KEY=<your groq key>
GRIMOIRE_MCP_TOKEN=<run: openssl rand -hex 32>
GRIMOIRE_PUBLIC_ORIGINS=https://grimoire.aquryu.space
CLOUDFLARE_TUNNEL_TOKEN=<the tunnel token from Step 1>
```

Start it, then pull the embedding model once:

```bash
docker compose up -d --build
docker compose exec ollama ollama pull nomic-embed-text
# optional local completion fallback (Groq is primary, so this is not required):
# docker compose exec ollama ollama pull llama3.2
```

Check it:

```bash
docker compose ps
docker compose logs -f cloudflared    # should show the tunnel registering
```

`https://grimoire.aquryu.space` should load the dashboard. The MCP endpoint is
`https://mcp.aquryu.space/mcp`.

---

## Step 3 — Lock it down

**Dashboard (`grimoire.aquryu.space`) -> Cloudflare Access.**
The dashboard has no login of its own, so put it behind Access:

1. Zero Trust -> **Access -> Applications -> Add an application -> Self-hosted**.
2. Subdomain `grimoire`, domain `aquryu.space`.
3. Add a policy: Action **Allow**, rule **Emails** = your email (you will get a
   one-time code to log in). Save.

**MCP endpoint (`mcp.aquryu.space`).**
It is already protected by the bearer token (`GRIMOIRE_MCP_TOKEN`): every request
without `Authorization: Bearer <token>` gets a 401. That is enough for agents.

Optional extra layer, a Cloudflare Access **service token** so only your machines
reach the origin at all:

1. Zero Trust -> Access -> **Service Auth -> Create Service Token**. Copy the Client
   ID and Secret.
2. Add an Access application for `mcp.aquryu.space` with a policy of type
   **Service Auth** referencing that token.
3. Agents then send `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers (see
   below) in addition to the bearer token.

---

## Step 4 — Connect your agents

The endpoint is `https://mcp.aquryu.space/mcp`. The header is
`Authorization: Bearer <GRIMOIRE_MCP_TOKEN>`.

**Gemini CLI** (`~/.gemini/settings.json`):

```json
{
  "mcpServers": {
    "grimoire": {
      "httpUrl": "https://mcp.aquryu.space/mcp",
      "headers": { "Authorization": "Bearer <GRIMOIRE_MCP_TOKEN>" }
    }
  }
}
```

**Claude Code / Codex / Cursor** (any client that takes a remote MCP URL): point it
at the same URL with the same `Authorization` header. For Claude Code:

```bash
claude mcp add --transport http grimoire https://mcp.aquryu.space/mcp \
  --header "Authorization: Bearer <GRIMOIRE_MCP_TOKEN>"
```

If you also enabled the Access **service token** in Step 3, add these headers too:

```
CF-Access-Client-Id: <client id>
CF-Access-Client-Secret: <client secret>
```

Now any of those agents can call the `kb_*` tools (retrieve, today, create_task,
generate_day, ...) against the same store. Heavy or high-volume work can run on
Gemini Flash while the data stays in one place.

---

## Updating, backups, troubleshooting

- **Update:** `git pull && docker compose up -d --build` in `deploy/`.
- **Backup:** the store is the `grimoire_data` volume.
  `docker compose exec grimoire python -m grimoire.backup` (or copy the volume).
- **MCP returns 401:** the `Authorization` header is missing or the token does not
  match `GRIMOIRE_MCP_TOKEN`.
- **Retrieval fails / 503:** the embedding model is not pulled, run the
  `ollama pull nomic-embed-text` step.
- **Tunnel not connecting:** check `docker compose logs cloudflared` and that the
  token in `.env` matches the tunnel from Step 1.

---

## Note on scope

The project's `CLAUDE.md` is written for a single local instance ("no multi-user, no
cloud sync"). This deployment is still single-user, it just moves that one instance
onto your own server and reaches it over your domain, the same trust model as your
self-hosted n8n. Keep `GRIMOIRE_MCP_TOKEN` secret and the dashboard behind Access.
