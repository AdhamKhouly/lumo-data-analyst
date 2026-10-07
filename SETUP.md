# Setup

## 1. Python environment

Python 3.11 or newer.

```bash
git clone <this repository>
cd lumo-data-analyst
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Build the database

```bash
python -m src.ingest
```

This reads every workbook under `data/Week N/` and writes `lumo.duckdb` in the project
folder. It prints how many files were parsed and any warnings (Weeks 2 and 3 have no
product-sales table in their receipts, which is expected). Run it again after adding or
changing a report; unchanged files are skipped.

Options: `--data <folder>`, `--db <file>`, `--force` (re-parse everything), `-v`.

## 3. Try the functions without Claude

Any function can be called directly, which is useful for seeing exactly what Lumo works from:

```bash
python -m src.chat --tool get_metric '{"metric": "revenue", "week": 7}'
python -m src.chat --tool compare_metric '{"metric": "customer satisfaction", "start_week": 1, "end_week": 14}'
python -m src.chat --tool metric_trend '{"metric": "wait time", "start_week": 10}'
python -m src.chat --tool search_comments '{"query": "lines", "start_week": 10}'
python -m src.chat --tool fit_regression '{"target": "revenue", "predictors": ["employees"]}'
python -m src.chat --tool evaluate_scenario '{"changes": {"extra_employees": 4}}'
python -m src.chat --tool plan_next_week '{"objective": "net_income"}'
```

The full list of functions is in `TOOLS` in `src/agent.py`.

## 4. Chat in the terminal

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (from
https://console.anthropic.com/). Then:

```bash
python -m src.chat
python -m src.chat --ask "How did revenue change from week 3 to week 8?"
python -m src.chat --show-tools      # also prints which functions were called
```

`CLAUDE_MODEL` in `.env` changes the model (default `claude-opus-5-5`).

## 5. Discord bot

You need a Discord application. In the [Developer Portal](https://discord.com/developers/applications):

1. **New Application**, give it a name.
2. **Bot** tab: under *Privileged Gateway Intents* turn on **Message Content Intent**.
   Then **Reset Token**, copy the token into `.env` as `DISCORD_BOT_TOKEN`.
3. **OAuth2 > URL Generator**: tick the `bot` and `applications.commands` scopes, and under
   bot permissions tick *View Channel*, *Send Messages* and *Read Message History*. Open the
   generated URL to invite the bot to your server.

Then:

```bash
python -m src.discord_bot
```

In a server, @mention the bot to ask a question. In a DM, just type. If you want a channel
where no mention is needed, put its ID in `DISCORD_CHANNEL_IDS` (enable Developer Mode in
Discord, right-click the channel, *Copy Channel ID*). `DISCORD_ALLOWED_USER_IDS` restricts
who may use the bot; leave it empty to allow everyone who can reach it.

Slash commands: `/clear` forgets your conversation, `/weeks` shows what data is loaded.

Each user gets their own conversation per channel, so follow-up questions work and two
people never share context. Conversations live in memory and are forgotten when the bot
restarts.

## 6. Tests

```bash
python -m pytest
```

No test calls the Anthropic API or Discord. The tests that use the real workbooks are
skipped automatically if the `data/` folder is missing.

## 7. README charts

```bash
python scripts/make_charts.py
```

Regenerates the three images in `assets/` from the data in `data/` (it uses `lumo.duckdb`
if it exists, otherwise it parses the workbooks into memory).

## Troubleshooting

| Problem | What to do |
|---|---|
| `Could not open lumo.duckdb` | run `python -m src.ingest` first |
| `DISCORD_BOT_TOKEN is not set` | copy `.env.example` to `.env` and fill it in |
| Discord says the intent is missing | enable *Message Content Intent* on the Bot tab |
| the bot ignores messages in a server | @mention it, or add the channel to `DISCORD_CHANNEL_IDS`; check it has *View Channel* permission |
| `anthropic.AuthenticationError` | check `ANTHROPIC_API_KEY` in `.env` |
| DuckDB "lock" error | only one process can write the database; stop the bot before running ingest, or vice versa |
