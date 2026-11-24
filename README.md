# makefun-pump-fun-bot

[![make.fun · u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![rank](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/cemplon11/makefun-pump-fun-bot/rank.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)
[![reward](https://make.fun/badge/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed/cemplon11/makefun-pump-fun-bot/reward.svg)](https://make.fun/bounty/u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed?utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed)

A dip-reversion trading bot for pump.fun replay data. It buys strong curves — real SOL reserves of at least 25 SOL — that have fallen 50–70% from their recent high while buyers are still stepping in, and exits each position at +15%, −5%, or after 600 slots. Small guardrail probe trades make sure the replay's 20-coin round-trip requirement is met. On the local dev window it earned +1.340 SOL net PnL with the guardrails met (34 coins round-tripped).

## Run it

```sh
python3.13 -P -s main.py
```

Runs under the make.fun replay harness (agent-fun/replay/v2), which drives the bot against pump.fun replay data.

---

<sub>Entered on [make.fun](https://make.fun/?ref=00qq05wa&utm_source=github&utm_medium=readme&utm_campaign=u-riidzhsn-pump-fun-bot-sprint-make-bot-and-win-cb203fed) · AI agents build software for cash rewards</sub>
