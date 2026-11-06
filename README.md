# The Salt Ship

A text-based pub simulation set in Nantwich. An AI landlord runs the pub, and customers have memories, grudges, rumours and opinions. Each day produces a landlord's log, customer diaries and a paper.

## Run it

    python3 world.py 3            # play three in-game days
    python3 world.py 1 --reset    # start a new world
    python3 world.py 5 --seed 42  # repeatable run

Write-ups go to `days/` and the saved world to `state.json` (both git-ignored).

## Layout

- `world.py`: world state, rules engine, landlord brain, scenes and write-ups
- `memory.py`: memories, relationships, opinions and retrieval
- `news.py`: local news loader; drop `.txt` or `.md` articles in `news/`

The landlord brain is a rules-based stand-in for now. It is designed to be swapped for an LLM that reads the same state and returns the same action list.

## Model modes

    python3 world.py 3                          # rules only, no model, no cost
    SALT_LLM=mock python3 world.py 3            # pipeline test with canned replies, no cost
    SALT_LLM=anthropic ANTHROPIC_API_KEY=... python3 world.py 3   # real model

With a model on, the landlord decides up to three times a day, and each hour the room gets one batched scene call. Every call counts against `SALT_DAILY_CALLS` (default 40), kept in `budget.json`. When the cap is reached, or a call fails, the sim falls back to the rules. Model output is only proposals: the rules engine checks every action and memories are clamped.

Set `SALT_MODEL` to change the model name (default `claude-haiku-5-5`).
