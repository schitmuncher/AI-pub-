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
